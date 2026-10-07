"""Postgres setup for isolated test runs (POSTHOG_TEST_ISOLATION, see posthog/settings/data_stores.py).

An isolated run gets its own test databases. Building one with Django migrations replays the whole
migration history, so the first run clones the shared, already migrated test databases with
``CREATE DATABASE ... TEMPLATE`` instead, and Django's keepdb path then applies only the migrations the
clone lacks. Wired in by the root conftest.py through pytest-django's ``django_db_modify_db_settings``.
"""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from django.conf import settings

import psycopg
from psycopg import sql

from posthog.product_db_config import load_product_db_routes

# How long to wait for other sessions to leave a shared test database before the run stops. A stopped run
# costs a retry, while building the databases by migrating is what isolation exists to avoid, so the wait is generous.
TEMPLATE_WAIT_SECONDS = 300.0
# The check is a cheap pg_stat_activity read, so poll often enough to catch the gap between two runs of another agent.
TEMPLATE_POLL_SECONDS = 1.0

# `hogli test:isolated:clean` reads this application_name in pg_stat_activity to skip runs in progress.
APPLICATION_NAME_PREFIX = "posthog-test-isolation:"


class IsolatedRunConflict(Exception):
    pass


class SharedDatabaseBusy(Exception):
    pass


def configure_product_test_databases() -> None:
    # pytest-django appends the worker suffix last, but product setup appends the product name last.
    default = settings.DATABASES["default"]
    database = default["TEST"]["NAME"] or f"test_{default['NAME']}"
    for route in load_product_db_routes(settings.BASE_DIR):
        alias = f"{route.database}_db_writer"
        if alias in settings.DATABASES:
            settings.DATABASES[alias]["TEST"]["NAME"] = f"{database}_{route.database}"


@contextmanager
def isolated_run() -> Iterator[psycopg.Connection]:
    default = settings.DATABASES["default"]
    database = default["TEST"]["NAME"]
    with psycopg.connect(
        host=default.get("HOST") or None,
        port=default.get("PORT") or None,
        user=default.get("USER") or None,
        password=default.get("PASSWORD") or None,
        dbname="postgres",
        autocommit=True,
        application_name=f"{APPLICATION_NAME_PREFIX}{settings.TEST_ISOLATION_NAME}",
    ) as connection:
        # The advisory lock lives as long as this connection, so a crashed run never leaves a stale lock behind.
        row = connection.execute(
            "SELECT pg_try_advisory_lock(hashtext(%s))", (f"posthog-test-isolation:{database}",)
        ).fetchone()
        if row != (True,):
            raise IsolatedRunConflict(
                f"Another test run is using the isolated databases {database}. Wait for it to finish, or "
                "pick another name with `hogli test <path> --isolated <name>` or POSTHOG_TEST_ISOLATION=<name>."
            )
        yield connection


def _has_sessions(connection: psycopg.Connection, database: str) -> bool:
    # Postgres refuses to copy a database that has other sessions. CREATE DATABASE also blocks new
    # connections to the template while it waits for them to leave, so check first instead of letting
    # every attempt stall the other test run.
    row = connection.execute("SELECT EXISTS (SELECT FROM pg_stat_activity WHERE datname = %s)", (database,)).fetchone()
    return row == (True,)


def _clone_database(
    connection: psycopg.Connection, database: str, template: str, deadline: float, announce: Callable[[str], None]
) -> None:
    existing = {
        name
        for (name,) in connection.execute(
            "SELECT datname FROM pg_database WHERE datname = ANY(%s)", ([database, template],)
        ).fetchall()
    }
    if database in existing or template not in existing:
        return

    started = time.monotonic()
    announced_wait = False
    while True:
        if not _has_sessions(connection, template):
            try:
                connection.execute(
                    sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(database), sql.Identifier(template))
                )
            except psycopg.errors.ObjectInUse:
                pass  # a session connected between the check and the copy
            else:
                announce(f"Cloned {template} into {database} in {time.monotonic() - started:.1f} s")
                return
        if time.monotonic() + TEMPLATE_POLL_SECONDS > deadline:
            raise SharedDatabaseBusy(
                f"{template} stayed in use for {time.monotonic() - started:.0f} s, so it cannot be cloned into {database}. "
                f"Let the test run on {template} finish and run this again, or pass --create-db to build {database} "
                "by running every migration."
            )
        if not announced_wait:
            announce(f"Waiting for other sessions to leave {template} so it can be cloned into {database}")
            announced_wait = True
        time.sleep(TEMPLATE_POLL_SECONDS)


def clone_test_databases(connection: psycopg.Connection, announce: Callable[[str], None]) -> None:
    default = settings.DATABASES["default"]
    database = default["TEST"]["NAME"]
    shared = f"test_{default['NAME']}"
    deadline = time.monotonic() + TEMPLATE_WAIT_SECONDS
    _clone_database(connection, database, shared, deadline, announce)
    _clone_database(connection, f"{database}_persons", f"{shared}_persons", deadline, announce)
