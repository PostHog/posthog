import os

import pytest
from unittest.mock import patch

from posthog.persons_db import LOCAL_DEV_PERSONS_DB_URL, persons_db_aconnection, persons_db_connection, persons_db_url


class TestPersonsDbUrl:
    def test_writer_uses_writer_env(self):
        with patch.dict(os.environ, {"PERSONS_DB_WRITER_URL": "postgres://w@host:5432/db"}):
            assert persons_db_url(writer=True) == "postgres://w@host:5432/db"

    def test_reader_uses_reader_env(self):
        with patch.dict(os.environ, {"PERSONS_DB_READER_URL": "postgres://r@host:5432/db"}):
            assert persons_db_url(writer=False) == "postgres://r@host:5432/db"

    def test_reader_falls_back_to_writer_when_no_reader_env(self):
        with patch.dict(os.environ, {"PERSONS_DB_WRITER_URL": "postgres://w@host:5432/db"}):
            os.environ.pop("PERSONS_DB_READER_URL", None)
            assert persons_db_url(writer=False) == "postgres://w@host:5432/db"

    def test_local_default_when_unset(self):
        with patch.dict(os.environ):
            os.environ.pop("PERSONS_DB_WRITER_URL", None)
            os.environ.pop("PERSONS_DB_READER_URL", None)
            assert persons_db_url(writer=True) == LOCAL_DEV_PERSONS_DB_URL
            assert persons_db_url(writer=False) == LOCAL_DEV_PERSONS_DB_URL


@pytest.mark.django_db()
def test_sync_connection_targets_persons_db():
    with persons_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        row = cursor.fetchone()
    assert row is not None
    assert row[0].endswith("_persons")


@pytest.mark.django_db()
def test_sync_reader_connection_works():
    with persons_db_connection(writer=False) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)


@pytest.mark.django_db()
async def test_async_connection_targets_persons_db():
    async with persons_db_aconnection() as conn, conn.cursor() as cursor:
        await cursor.execute("SELECT current_database()")
        row = await cursor.fetchone()
    assert row is not None
    assert row[0].endswith("_persons")
