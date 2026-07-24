"""Postgres client for the duckgres DWH (ducklake proxy)."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import psycopg
from psycopg.rows import DictRow, dict_row

_CONNECT_TIMEOUT_SECONDS = 15
_STATEMENT_TIMEOUT_MS = 10 * 60 * 1000


class DuckgresNotConfiguredError(RuntimeError):
    """Raised when DUCKGRES_PG_URL is not set in the environment."""


@contextmanager
def duckgres_cursor() -> Iterator[psycopg.Cursor[DictRow]]:
    """Yield a dict-row cursor bound to a short-lived duckgres connection.

    The connection runs in autocommit mode so each statement stands alone: the
    duckgres/ducklake backend doesn't honor a transaction-scoped ``SET LOCAL``
    the way real Postgres does, and running one inside an implicit transaction
    left it aborted so the following query failed with "current transaction is
    aborted". The statement timeout is instead requested at connection startup
    via libpq ``options`` so a runaway analytics query can't pin the worker —
    the caller is expected to paginate large result sets.
    """
    pg_url = os.environ.get("DUCKGRES_PG_URL")
    if not pg_url:
        raise DuckgresNotConfiguredError("DUCKGRES_PG_URL is not set")

    with psycopg.connect(
        pg_url,
        connect_timeout=_CONNECT_TIMEOUT_SECONDS,
        row_factory=dict_row,
        autocommit=True,
        options=f"-c statement_timeout={_STATEMENT_TIMEOUT_MS}",
    ) as conn:
        with conn.cursor() as cur:
            yield cast(psycopg.Cursor[DictRow], cur)
