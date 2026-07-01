"""Direct, off-ORM connections to the persons database.

Cold admin/utility paths — Temporal activities, management commands, Dagster jobs —
that are too bespoke for the personhog gRPC client connect to the persons database
through this module. It returns raw psycopg connections that do **not** go through
Django's ORM, connection pool, or database router, so the persons database can be
dropped from Django's ``DATABASES`` without affecting these paths.

The connection URL is sourced only from the environment:

- ``PERSONS_DB_WRITER_URL`` — primary read/write endpoint
- ``PERSONS_DB_READER_URL`` — read replica, falling back to the writer URL

Production injects these via the Helm charts and the test suite sets them in
``conftest``; only local development relies on the localhost default below.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

import psycopg

# Local-development fallback only. Every deployment that runs this code injects
# PERSONS_DB_{WRITER,READER}_URL (charts for prod, conftest for tests), so this is
# used solely when a developer has neither set locally. The host/credentials mirror
# the Django persons-DB config (posthog/settings/data_stores.py), so the fallback
# resolves to the same local database whether or not Django is in the loop.
LOCAL_DEV_PERSONS_DB_URL = (
    f"postgres://{os.getenv('PGUSER', 'posthog')}:{os.getenv('PGPASSWORD', 'posthog')}"
    f"@{os.getenv('PGHOST', 'db')}:{os.getenv('PGPORT', '5432')}/posthog_persons"
)


def persons_db_url(*, writer: bool = True) -> str:
    """Resolve the persons-database connection URL from the environment.

    The writer uses ``PERSONS_DB_WRITER_URL``; the reader uses
    ``PERSONS_DB_READER_URL`` and falls back to the writer URL when no dedicated
    reader endpoint is configured (mirroring production). Falls back to a local
    default (derived from the PG* env vars) only when nothing is set, i.e. local development.
    """
    if writer:
        return os.getenv("PERSONS_DB_WRITER_URL") or LOCAL_DEV_PERSONS_DB_URL
    return os.getenv("PERSONS_DB_READER_URL") or os.getenv("PERSONS_DB_WRITER_URL") or LOCAL_DEV_PERSONS_DB_URL


@contextmanager
def persons_db_connection(*, writer: bool = True, autocommit: bool = False) -> Iterator[psycopg.Connection[Any]]:
    """Synchronous raw psycopg connection to the persons database (context-managed)."""
    with psycopg.connect(persons_db_url(writer=writer), autocommit=autocommit) as conn:
        yield conn


@asynccontextmanager
async def persons_db_aconnection(
    *, writer: bool = True, autocommit: bool = False
) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    """Asynchronous raw psycopg connection to the persons database (context-managed)."""
    async with await psycopg.AsyncConnection.connect(persons_db_url(writer=writer), autocommit=autocommit) as conn:
        yield conn
