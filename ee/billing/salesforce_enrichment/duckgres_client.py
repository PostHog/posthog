"""Postgres client for the duckgres DWH (ducklake proxy)."""

from collections.abc import Iterator
from contextlib import contextmanager

from django.conf import settings

import psycopg
from psycopg import sql
from psycopg.rows import DictRow, dict_row

_CONNECT_TIMEOUT_SECONDS = 15
_STATEMENT_TIMEOUT_MS = 10 * 60 * 1000


class DuckgresNotConfiguredError(RuntimeError):
    """Raised when DUCKGRES_PG_URL is not set in the environment."""


@contextmanager
def duckgres_cursor() -> Iterator[psycopg.Cursor[DictRow]]:
    """Yield a dict-row cursor bound to a short-lived duckgres connection.

    A per-session statement timeout is set so a runaway analytics query cannot
    pin the worker — the caller is expected to paginate large result sets.
    """
    if not settings.DUCKGRES_PG_URL:
        raise DuckgresNotConfiguredError("DUCKGRES_PG_URL is not set")

    with psycopg.connect(
        settings.DUCKGRES_PG_URL,
        connect_timeout=_CONNECT_TIMEOUT_SECONDS,
        row_factory=dict_row,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(_STATEMENT_TIMEOUT_MS)))
            yield cur
