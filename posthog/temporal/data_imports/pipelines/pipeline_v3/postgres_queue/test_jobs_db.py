from typing import Any

import pytest

import psycopg

from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
    STATUS_TABLE,
    STATUS_VIEW,
    BatchQueue,
    PendingBatch,
)


def _get_test_database_url() -> str:
    from django.db import connection

    s = connection.settings_dict
    host = s.get("HOST", "localhost") or "localhost"
    port = s.get("PORT", "5432") or "5432"
    return f"postgres://{s['USER']}:{s['PASSWORD']}@{host}:{port}/{s['NAME']}"


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
    conn.execute(f"DROP VIEW IF EXISTS {STATUS_VIEW}")
    conn.execute(f"""
        CREATE VIEW {STATUS_VIEW} AS
        SELECT DISTINCT ON (batch_id) *
        FROM {STATUS_TABLE}
        ORDER BY batch_id ASC, created_at DESC, id DESC
    """)


def _truncate_tables(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"TRUNCATE {STATUS_TABLE}, {BATCH_TABLE} RESTART IDENTITY CASCADE")


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
    params = {**_BATCH_DEFAULTS, **overrides}
    return await BatchQueue.insert(conn, **params)


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


@pytest.fixture
async def conn_b(_db_url: str):
    async with await psycopg.AsyncConnection.connect(_db_url, autocommit=True) as c:
        yield c


@pytest.mark.django_db(transaction=True)
class TestBatchQueueInsert:
    @pytest.mark.asyncio
    async def test_insert_returns_uuid(self, conn):
        batch_id = await _insert_batch(conn)

        assert len(batch_id) == 36
        assert batch_id.count("-") == 4

    @pytest.mark.asyncio
    async def test_insert_unique_ids(self, conn):
        id1 = await _insert_batch(conn, batch_index=0)
        id2 = await _insert_batch(conn, batch_index=1)

        assert id1 != id2


@pytest.mark.django_db(transaction=True)
class TestBatchQueueGetUnprocessed:
    @pytest.mark.asyncio
    async def test_returns_new_batches(self, conn):
        await _insert_batch(conn, batch_index=0)
        await _insert_batch(conn, batch_index=1)
        await _insert_batch(conn, batch_index=2)

        batches = await BatchQueue.get_unprocessed_and_lock(conn)

        assert len(batches) == 3
        assert sorted(b.batch_index for b in batches) == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_skips_succeeded_batches(self, conn):
        bid = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=bid, job_state="succeeded", attempt=1)

        batches = await BatchQueue.get_unprocessed_and_lock(conn)

        assert len(batches) == 0

    @pytest.mark.asyncio
    async def test_returns_waiting_retry_batches(self, conn):
        bid = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=bid, job_state="waiting_retry", attempt=1)

        batches = await BatchQueue.get_unprocessed_and_lock(conn)

        assert len(batches) == 1
        assert batches[0].latest_attempt == 1

    @pytest.mark.asyncio
    async def test_skips_entire_failed_run(self, conn):
        await _insert_batch(conn, batch_index=0, run_uuid="run-fail")
        bid2 = await _insert_batch(conn, batch_index=1, run_uuid="run-fail")
        await BatchQueue.update_status(conn, batch_id=bid2, job_state="failed", attempt=1)

        batches = await BatchQueue.get_unprocessed_and_lock(conn)

        assert len(batches) == 0

    @pytest.mark.asyncio
    async def test_respects_limit(self, conn):
        for i in range(10):
            await _insert_batch(conn, batch_index=i)

        batches = await BatchQueue.get_unprocessed_and_lock(conn, limit=3)

        assert len(batches) == 3


@pytest.mark.django_db(transaction=True)
class TestBatchQueueUpdateStatus:
    @pytest.mark.asyncio
    async def test_appends_multiple_statuses(self, conn):
        bid = await _insert_batch(conn)

        await BatchQueue.update_status(conn, batch_id=bid, job_state="executing", attempt=1)
        await BatchQueue.update_status(conn, batch_id=bid, job_state="succeeded", attempt=1)

        row = await conn.execute(f"SELECT count(*) FROM {STATUS_TABLE} WHERE batch_id = %s", [bid])
        count = (await row.fetchone())[0]
        assert count == 2


@pytest.mark.django_db(transaction=True)
class TestBatchQueueFailRun:
    @pytest.mark.asyncio
    async def test_fails_only_pending_batches(self, conn):
        bid1 = await _insert_batch(conn, batch_index=0, run_uuid="run-x")
        await _insert_batch(conn, batch_index=1, run_uuid="run-x")
        await _insert_batch(conn, batch_index=2, run_uuid="run-x")
        await BatchQueue.update_status(conn, batch_id=bid1, job_state="succeeded", attempt=1)

        count = await BatchQueue.fail_run(conn, run_uuid="run-x", reason="test failure")

        assert count == 2

        batches = await BatchQueue.get_unprocessed_and_lock(conn)
        assert len(batches) == 0


@pytest.mark.django_db(transaction=True)
class TestBatchQueueAdvisoryLocks:
    @pytest.mark.asyncio
    async def test_unlock_for_batches_releases_locks(self, conn, conn_b):
        await _insert_batch(conn, team_id=1, schema_id="s1", batch_index=0)
        await _insert_batch(conn, team_id=1, schema_id="s1", batch_index=1)
        await _insert_batch(conn, team_id=1, schema_id="s1", batch_index=2)

        batches = await BatchQueue.get_unprocessed_and_lock(conn)
        assert len(batches) == 3

        batches_b = await BatchQueue.get_unprocessed_and_lock(conn_b)
        assert len(batches_b) == 0, "conn_b should not acquire lock held by conn"

        await BatchQueue.unlock_for_batches(conn, batches=batches)

        batches_b = await BatchQueue.get_unprocessed_and_lock(conn_b)
        assert len(batches_b) == 3, "conn_b should acquire lock after conn released it"

        await BatchQueue.unlock_for_batches(conn_b, batches=batches_b)

    @pytest.mark.asyncio
    async def test_different_keys_lock_independently(self, conn, conn_b):
        await _insert_batch(conn, team_id=1, schema_id="s1")
        await _insert_batch(conn, team_id=2, schema_id="s2")

        batches_a = await BatchQueue.get_unprocessed_and_lock(conn)
        assert len(batches_a) == 2

        await BatchQueue.unlock_for_batches(conn, batches=[b for b in batches_a if b.schema_id == "s1"])

        batches_b = await BatchQueue.get_unprocessed_and_lock(conn_b)
        assert len(batches_b) == 1
        assert batches_b[0].schema_id == "s1"

        await BatchQueue.unlock_for_batches(conn, batches=[b for b in batches_a if b.schema_id == "s2"])
        await BatchQueue.unlock_for_batches(conn_b, batches=batches_b)


@pytest.mark.django_db(transaction=True)
class TestBatchQueueStaleExecuting:
    @pytest.mark.asyncio
    async def test_finds_orphaned_executing_batches(self, conn, conn_b, _db_url):
        bid = await _insert_batch(conn)

        async with await psycopg.AsyncConnection.connect(_db_url, autocommit=True) as orphan_conn:
            await BatchQueue.get_unprocessed_and_lock(orphan_conn)
            await BatchQueue.update_status(orphan_conn, batch_id=bid, job_state="executing", attempt=1)
        # orphan_conn is now closed — advisory lock released

        stale = await BatchQueue.get_stale_executing(conn)
        assert len(stale) == 1
        assert str(stale[0].id) == bid
        assert stale[0].latest_attempt == 1

    @pytest.mark.asyncio
    async def test_does_not_find_actively_held_batches(self, conn, conn_b):
        bid = await _insert_batch(conn)

        await BatchQueue.get_unprocessed_and_lock(conn)
        await BatchQueue.update_status(conn, batch_id=bid, job_state="executing", attempt=1)

        stale = await BatchQueue.get_stale_executing(conn_b)
        assert len(stale) == 0

        await conn.execute("SELECT pg_advisory_unlock_all()")


class TestPendingBatchToExportSignal:
    def test_maps_all_fields(self):
        batch = PendingBatch(
            id="00000000-0000-0000-0000-000000000001",
            team_id=42,
            schema_id="schema-1",
            source_id="source-1",
            job_id="job-1",
            run_uuid="run-1",
            batch_index=3,
            s3_path="s3://bucket/data.parquet",
            row_count=500,
            byte_size=2048,
            is_final_batch=True,
            total_batches=4,
            total_rows=2000,
            sync_type="incremental",
            cumulative_row_count=1500,
            resource_name="users",
            is_resume=True,
            is_first_ever_sync=False,
            metadata={
                "timestamp_ns": 123456789,
                "data_folder": "/tmp/data",
                "primary_keys": ["id"],
                "cdc_write_mode": "upsert",
            },
            latest_attempt=2,
        )

        signal = batch.to_export_signal()

        assert signal["team_id"] == 42
        assert signal["job_id"] == "job-1"
        assert signal["schema_id"] == "schema-1"
        assert signal["batch_index"] == 3
        assert signal["is_final_batch"] is True
        assert signal["total_batches"] == 4
        assert signal["sync_type"] == "incremental"
        assert signal["cumulative_row_count"] == 1500
        assert signal["is_resume"] is True
        assert signal["timestamp_ns"] == 123456789
        assert signal["data_folder"] == "/tmp/data"
        assert signal["primary_keys"] == ["id"]
        assert signal["cdc_write_mode"] == "upsert"
