from pathlib import Path
from typing import NamedTuple
from datetime import date
import shutil
import asyncio

import aiosql

# for sqlite3
def todate(year, month, day):
    return f"{year}-{month:02}-{day:02}"


def has_exec(cmd):
    return shutil.which(cmd) is not None


class UserBlogSummary(NamedTuple):
    title: str
    published: date


RECORD_CLASSES = {"UserBlogSummary": UserBlogSummary}


def queries(driver):
    dir_path = Path(__file__).parent / "blogdb" / "sql"
    return aiosql.from_path(dir_path, driver, RECORD_CLASSES)


# run something on a connection without a schema
def run_something(conn):
    def sel12(cur):
        cur.execute("SELECT 1, 'un' UNION SELECT 2, 'deux' ORDER BY 1")
        res = cur.fetchall()
        assert res == ((1, "un"), (2, "deux"))

    cur = conn.cursor()
    has_with = hasattr(cur, "__enter__")
    sel12(cur)
    cur.close()

    if has_with:  # if available
        with conn.cursor() as cur:
            sel12(cur)

    conn.commit()


def run_record_query(conn, queries):
    actual = queries.users.get_all(conn)
    assert len(actual) == 3
    assert actual[0] == {
        "userid": 1,
        "username": "bobsmith",
        "firstname": "Bob",
        "lastname": "Smith",
    }


def run_parameterized_query(conn, queries):
    actual = queries.users.get_by_lastname(conn, lastname="Doe")
    expected = [(3, "janedoe", "Jane", "Doe"), (2, "johndoe", "John", "Doe")]
    # NOTE mysqldb returns a tuple instead of a list, hence the conversion
    assert list(actual) == expected


def run_parameterized_record_query(conn, queries, db, todate):
    fun = (
        queries.blogs.sqlite_get_blogs_published_after
        if db == "sqlite"
        else queries.blogs.pg_get_blogs_published_after
        if db == "pg"
        else queries.blogs.my_get_blogs_published_after
    )

    actual = fun(conn, published=todate(2018, 1, 1))

    expected = [
        {"title": "How to make a pie.", "username": "bobsmith", "published": "2018-11-23 00:00"},
        {"title": "Testing", "username": "janedoe", "published": "2018-01-01 00:00"},
    ]

    assert actual == expected


def run_record_class_query(conn, queries, todate):
    actual = queries.blogs.get_user_blogs(conn, userid=1)
    expected = [
        UserBlogSummary(title="How to make a pie.", published=todate(2018, 11, 23)),
        UserBlogSummary(title="What I did Today", published=todate(2017, 7, 28)),
    ]

    assert all(isinstance(row, UserBlogSummary) for row in actual)
    assert actual == expected

    one = queries.blogs.get_latest_user_blog(conn, userid=1)
    assert one == UserBlogSummary(title="How to make a pie.", published=todate(2018, 11, 23))


def run_select_cursor_context_manager(conn, queries, todate):
    with queries.blogs.get_user_blogs_cursor(conn, userid=1) as cursor:
        actual = cursor.fetchall()
        expected = [
            ("How to make a pie.", todate(2018, 11, 23)),
            ("What I did Today", todate(2017, 7, 28)),
        ]
        assert list(actual) == expected


def run_select_one(conn, queries):
    actual = queries.users.get_by_username(conn, username="johndoe")
    expected = (2, "johndoe", "John", "Doe")
    assert actual == expected


def run_insert_returning(conn, queries, db, todate):
    fun = (
        queries.blogs.publish_blog
        if db == "sqlite"
        else queries.blogs.pg_publish_blog
        if db == "pg"
        else queries.blogs.my_publish_blog
    )
    query = (
        "select blogid, title from blogs where blogid = %s;"
        if db == "pg"
        else "select blogid, title from blogs where blogid = ?;"
    )

    blogid = fun(
        conn,
        userid=2,
        title="My first blog",
        content="Hello, World!",
        published=todate(2018, 12, 4),
    )

    # sqlite returns a number while pg query returns a tuple
    if isinstance(blogid, tuple):
        blogid, title = blogid
    else:
        blogid, title = blogid, "My first blog"

    def check_cbt(cur, b, t):
        cur.execute(query, (b,))
        actual = cur.fetchone()
        assert actual == (b, t)

    cur = conn.cursor()
    has_with = hasattr(cur, "__enter__")
    check_cbt(cur, blogid, title)
    cur.close()

    # try with if available
    if has_with:
        with conn.cursor() as cur:
            check_cbt(cur, blogid, title)

    if db == "pg":
        res = queries.blogs.pg_no_publish(conn)
        assert res is None


def run_delete(conn, queries):
    # Removing the "janedoe" blog titled "Testing"
    actual = queries.blogs.remove_blog(conn, blogid=2)
    assert actual == 1

    janes_blogs = queries.blogs.get_user_blogs(conn, userid=3)
    assert len(janes_blogs) == 0


def run_insert_many(conn, queries, todate):
    blogs = [
        {
            "userid": 2,
            "title": "Blog Part 1",
            "content": "content - 1",
            "published": todate(2018, 12, 4),
        },
        {
            "userid": 2,
            "title": "Blog Part 2",
            "content": "content - 2",
            "published": todate(2018, 12, 5),
        },
        {
            "userid": 2,
            "title": "Blog Part 3",
            "content": "content - 3",
            "published": todate(2018, 12, 6),
        },
    ]

    actual = queries.blogs.pg_bulk_publish(conn, blogs)
    assert actual == 3

    johns_blogs = queries.blogs.get_user_blogs(conn, userid=2)
    assert johns_blogs == [
        ("Blog Part 3", todate(2018, 12, 6)),
        ("Blog Part 2", todate(2018, 12, 5)),
        ("Blog Part 1", todate(2018, 12, 4)),
    ]


def run_select_value(conn, queries):
    actual = queries.users.get_count(conn)
    assert actual == 3


#
# Asynchronous tests
#


async def run_async_record_query(conn, queries):
    actual = [dict(r) for r in await queries.users.get_all(conn)]

    assert len(actual) == 3
    assert actual[0] == {
        "userid": 1,
        "username": "bobsmith",
        "firstname": "Bob",
        "lastname": "Smith",
    }


async def run_async_parameterized_query(conn, queries, todate):
    actual = await queries.blogs.get_user_blogs(conn, userid=1)
    expected = [
        ("How to make a pie.", todate(2018, 11, 23)),
        ("What I did Today", todate(2017, 7, 28)),
    ]
    assert actual == expected


async def run_async_parameterized_record_query(conn, queries, db, todate):
    fun = (
        queries.blogs.pg_get_blogs_published_after
        if db == "pg"
        else queries.blogs.sqlite_get_blogs_published_after
    )
    records = await fun(conn, published=todate(2018, 1, 1))

    actual = [dict(rec) for rec in records]

    expected = [
        {"title": "How to make a pie.", "username": "bobsmith", "published": "2018-11-23 00:00"},
        {"title": "Testing", "username": "janedoe", "published": "2018-01-01 00:00"},
    ]

    assert actual == expected


async def run_async_record_class_query(conn, queries, todate):
    actual = await queries.blogs.get_user_blogs(conn, userid=1)

    expected = [
        UserBlogSummary(title="How to make a pie.", published=todate(2018, 11, 23)),
        UserBlogSummary(title="What I did Today", published=todate(2017, 7, 28)),
    ]

    assert all(isinstance(row, UserBlogSummary) for row in actual)
    assert actual == expected

    one = await queries.blogs.get_latest_user_blog(conn, userid=1)
    assert one == UserBlogSummary(title="How to make a pie.", published=todate(2018, 11, 23))


async def run_async_select_cursor_context_manager(conn, queries, todate):
    async with queries.blogs.get_user_blogs_cursor(conn, userid=1) as cursor:
        actual = [tuple(rec) async for rec in cursor]
        expected = [
            ("How to make a pie.", todate(2018, 11, 23)),
            ("What I did Today", todate(2017, 7, 28)),
        ]
        assert actual == expected


async def run_async_select_one(conn, queries):
    actual = await queries.users.get_by_username(conn, username="johndoe")
    expected = (2, "johndoe", "John", "Doe")
    assert actual == expected


async def run_async_select_value(conn, queries):
    actual = await queries.users.get_count(conn)
    expected = 3
    assert actual == expected


async def run_async_insert_returning(conn, queries, db, todate):

    fun = queries.blogs.pg_publish_blog if db == "pg" else queries.blogs.publish_blog

    blogid = await fun(
        conn,
        userid=2,
        title="My first blog",
        content="Hello, World!",
        published=todate(2018, 12, 4),
    )

    if db == "pg":
        blogid, title = blogid
    else:
        blogid, title = blogid, "My first blog"

    if db == "pg":
        query = "select blogid, title from blogs where blogid = $1;"
        actual = tuple(
            await conn.fetchrow(
                query,
                blogid,
            )
        )
    else:
        query = "select blogid, title from blogs where blogid = :blogid;"
        async with conn.execute(query, {"blogid": blogid}) as cur:
            actual = await cur.fetchone()
    assert actual == (blogid, title)


async def run_async_delete(conn, queries):
    # Removing the "janedoe" blog titled "Testing"
    actual = await queries.blogs.remove_blog(conn, blogid=2)
    assert actual is None

    janes_blogs = await queries.blogs.get_user_blogs(conn, userid=3)
    assert len(janes_blogs) == 0


async def run_async_insert_many(conn, queries, todate):
    blogs = [
        {
            "userid": 2,
            "title": "Blog Part 1",
            "content": "content - 1",
            "published": todate(2018, 12, 4),
        },
        {
            "userid": 2,
            "title": "Blog Part 2",
            "content": "content - 2",
            "published": todate(2018, 12, 5),
        },
        {
            "userid": 2,
            "title": "Blog Part 3",
            "content": "content - 3",
            "published": todate(2018, 12, 6),
        },
    ]
    actual = await queries.blogs.pg_bulk_publish(conn, blogs)
    assert actual is None

    johns_blogs = await queries.blogs.get_user_blogs(conn, userid=2)
    assert johns_blogs == [
        ("Blog Part 3", todate(2018, 12, 6)),
        ("Blog Part 2", todate(2018, 12, 5)),
        ("Blog Part 1", todate(2018, 12, 4)),
    ]


async def run_async_methods(conn, queries):
    users, sorted_users = await asyncio.gather(
        queries.users.get_all(conn), queries.users.get_all_sorted(conn)
    )

    assert [dict(u) for u in users] == [
        {"userid": 1, "username": "bobsmith", "firstname": "Bob", "lastname": "Smith"},
        {"userid": 2, "username": "johndoe", "firstname": "John", "lastname": "Doe"},
        {"userid": 3, "username": "janedoe", "firstname": "Jane", "lastname": "Doe"},
    ]
    assert [dict(u) for u in sorted_users] == [
        {"userid": 1, "username": "bobsmith", "firstname": "Bob", "lastname": "Smith"},
        {"userid": 3, "username": "janedoe", "firstname": "Jane", "lastname": "Doe"},
        {"userid": 2, "username": "johndoe", "firstname": "John", "lastname": "Doe"},
    ]
