from typing import Any

import pytest

import psycopg

from posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.jobs_db import (
    DUCKGRES_APPLY_TABLE,
    DUCKGRES_STATUS_TABLE,
    DUCKGRES_STATUS_VIEW,
    DuckgresBatchQueue,
)
from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
    STATUS_TABLE,
    STATUS_VIEW,
    BatchQueue,
)


def _get_test_database_url() -> str:
    from django.db import connection

    settings = connection.settings_dict
    host = settings.get("HOST", "localhost") or "localhost"
    port = settings.get("PORT", "5432") or "5432"
    return f"postgres://{settings['USER']}:{settings['PASSWORD']}@{host}:{port}/{settings['NAME']}"


def _ensure_tables(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {BATCH_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            team_id BIGINT NOT NULL,
            schema_id VARCHAR(200) NOT NULL,
            source_id VARCHAR(200) NOT NULL,
            job_id VARCHAR(200) NOT NULL,
            run_uuid VARCHAR(200) NOT NULL,
            batch_index INT NOT NULL,
            s3_path TEXT NOT NULL,
            row_count INT NOT NULL,
            byte_size BIGINT NOT NULL,
            is_final_batch BOOLEAN NOT NULL,
            total_batches INT,
            total_rows BIGINT,
            sync_type VARCHAR(32) NOT NULL,
            cumulative_row_count BIGINT NOT NULL DEFAULT 0,
            resource_name VARCHAR(400) NOT NULL,
            is_resume BOOLEAN NOT NULL DEFAULT FALSE,
            is_first_ever_sync BOOLEAN NOT NULL DEFAULT FALSE,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {STATUS_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id UUID NOT NULL REFERENCES {BATCH_TABLE}(id) ON DELETE CASCADE,
            job_state VARCHAR(32) NOT NULL,
            attempt SMALLINT NOT NULL DEFAULT 0,
            exec_time TIMESTAMPTZ,
            error_response JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {DUCKGRES_STATUS_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id UUID NOT NULL REFERENCES {BATCH_TABLE}(id) ON DELETE CASCADE,
            job_state VARCHAR(32) NOT NULL,
            attempt SMALLINT NOT NULL DEFAULT 0,
            exec_time TIMESTAMPTZ,
            error_response JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {DUCKGRES_APPLY_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            team_id BIGINT NOT NULL,
            schema_id VARCHAR(200) NOT NULL,
            run_uuid VARCHAR(200) NOT NULL,
            batch_index INT NOT NULL,
            batch_id UUID NOT NULL REFERENCES {BATCH_TABLE}(id) ON DELETE CASCADE,
            row_count INT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT sbdga_unique_batch_apply UNIQUE (team_id, schema_id, run_uuid, batch_index)
        )
    """)
    conn.execute(f"DROP VIEW IF EXISTS {STATUS_VIEW}")
    conn.execute(f"""
        CREATE VIEW {STATUS_VIEW} AS
        SELECT DISTINCT ON (batch_id) *
        FROM {STATUS_TABLE}
        ORDER BY batch_id ASC, created_at DESC, id DESC
    """)
    conn.execute(f"DROP VIEW IF EXISTS {DUCKGRES_STATUS_VIEW}")
    conn.execute(f"""
        CREATE VIEW {DUCKGRES_STATUS_VIEW} AS
        SELECT DISTINCT ON (batch_id) *
        FROM {DUCKGRES_STATUS_TABLE}
        ORDER BY batch_id ASC, created_at DESC, id DESC
    """)


def _truncate_tables(conn: psycopg.Connection[Any]) -> None:
    conn.execute(
        f"TRUNCATE {DUCKGRES_APPLY_TABLE}, {DUCKGRES_STATUS_TABLE}, {STATUS_TABLE}, {BATCH_TABLE} RESTART IDENTITY CASCADE"
    )


_BATCH_DEFAULTS: dict[str, Any] = {
    "team_id": 1,
    "schema_id": "schema-1",
    "source_id": "source-1",
    "job_id": "job-1",
    "run_uuid": "run-1",
    "batch_index": 0,
    "s3_path": "s3://bucket/path",
    "row_count": 100,
    "byte_size": 1024,
    "is_final_batch": False,
    "total_batches": None,
    "total_rows": None,
    "sync_type": "full_refresh",
    "cumulative_row_count": 0,
    "resource_name": "test_resource",
    "is_resume": False,
    "is_first_ever_sync": False,
    "metadata": {},
}


async def _insert_batch(conn: psycopg.AsyncConnection[Any], **overrides: Any) -> str:
    return await BatchQueue.insert(conn, **{**_BATCH_DEFAULTS, **overrides})


@pytest.fixture(scope="session")
def _db_url() -> str:
    return _get_test_database_url()


@pytest.fixture(scope="session", autouse=True)
def _create_tables(_db_url: str) -> None:
    with psycopg.Connection.connect(_db_url, autocommit=True) as conn:
        _ensure_tables(conn)


@pytest.fixture(autouse=True)
def _clean_tables(_db_url: str) -> None:
    with psycopg.Connection.connect(_db_url, autocommit=True) as conn:
        _truncate_tables(conn)
        conn.execute("SELECT pg_advisory_unlock_all()")


@pytest.fixture
async def conn(_db_url: str):
    async with await psycopg.AsyncConnection.connect(_db_url, autocommit=True) as c:
        yield c


@pytest.mark.django_db(transaction=True)
class TestDuckgresBatchQueueEligibility:
    @pytest.mark.asyncio
    async def test_ignores_batches_until_delta_succeeds(self, conn):
        await _insert_batch(conn)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)

        assert batches == []

    @pytest.mark.asyncio
    async def test_returns_delta_succeeded_batches(self, conn):
        batch_id = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)

        assert len(batches) == 1
        assert str(batches[0].id) == batch_id

    @pytest.mark.asyncio
    async def test_skips_duckgres_succeeded_batches(self, conn):
        batch_id = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)
        await DuckgresBatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)

        assert batches == []

    @pytest.mark.asyncio
    async def test_returns_duckgres_retry_batches(self, conn):
        batch_id = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)
        await DuckgresBatchQueue.update_status(conn, batch_id=batch_id, job_state="waiting_retry", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)

        assert len(batches) == 1
        assert batches[0].latest_attempt == 1

    @pytest.mark.asyncio
    async def test_enforces_prior_batch_apply_order(self, conn):
        first_id = await _insert_batch(conn, batch_index=0)
        second_id = await _insert_batch(conn, batch_index=1)
        await BatchQueue.update_status(conn, batch_id=first_id, job_state="succeeded", attempt=1)
        await BatchQueue.update_status(conn, batch_id=second_id, job_state="succeeded", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)

        assert [batch.batch_index for batch in batches] == [0]

    @pytest.mark.asyncio
    async def test_final_marker_waits_for_matching_data_batch_apply(self, conn):
        data_id = await _insert_batch(conn, batch_index=0, is_final_batch=False)
        final_id = await _insert_batch(conn, batch_index=0, is_final_batch=True, total_batches=1, total_rows=100)
        await BatchQueue.update_status(conn, batch_id=data_id, job_state="succeeded", attempt=1)
        await BatchQueue.update_status(conn, batch_id=final_id, job_state="succeeded", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)
        assert [str(batch.id) for batch in batches] == [data_id]

        await DuckgresBatchQueue.mark_applied(conn, batch=batches[0])
        await DuckgresBatchQueue.unlock_for_batches(conn, batches=batches)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)
        assert [str(batch.id) for batch in batches] == [final_id]

    @pytest.mark.asyncio
    async def test_delta_failed_run_is_skipped(self, conn):
        batch_id = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)
        failed_id = await _insert_batch(conn, batch_index=1)
        await BatchQueue.update_status(conn, batch_id=failed_id, job_state="failed", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)

        assert batches == []
