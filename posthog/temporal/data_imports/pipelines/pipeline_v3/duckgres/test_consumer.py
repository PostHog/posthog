from typing import Any

import pytest
from unittest.mock import AsyncMock, patch

from posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer import (
    DuckgresBatchConsumer,
    DuckgresConsumerConfig,
    _group_by_key,
)
from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import PendingBatch

from products.warehouse_sources_queue.backend.models import SourceBatchDuckgresStatus


def _make_batch(**overrides: Any) -> PendingBatch:
    defaults: dict[str, Any] = {
        "id": "00000000-0000-0000-0000-000000000001",
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
        "latest_attempt": 0,
    }
    defaults.update(overrides)
    return PendingBatch(**defaults)


def _make_consumer(max_attempts: int = 3, **kwargs) -> DuckgresBatchConsumer:
    config = DuckgresConsumerConfig(
        database_url="postgres://unused:unused@localhost/unused",
        max_attempts=max_attempts,
        **kwargs,
    )
    consumer = DuckgresBatchConsumer(config=config, process_batch=AsyncMock())
    consumer._conn = AsyncMock()
    consumer._recovery_conn = AsyncMock()
    return consumer


class TestDuckgresProcessSingle:
    @pytest.mark.asyncio
    async def test_adapter_forwards_empty_error_response_explicitly(self):
        consumer = _make_consumer()
        update_status_calls: list[dict[str, Any]] = []

        async def track_status(conn, **kwargs):
            update_status_calls.append(kwargs)

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.update_status",
                side_effect=track_status,
            ),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.has_applied",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            await consumer._process_single(_make_batch(is_final_batch=True))

        assert update_status_calls[0]["error_response"] is None
        assert update_status_calls[1]["error_response"] is None

    @pytest.mark.asyncio
    async def test_success_updates_status_and_marks_applied(self):
        consumer = _make_consumer()
        states: list[str] = []

        async def track_status(conn, *, batch_id, job_state, attempt, error_response=None):
            states.append(job_state)

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.update_status",
                side_effect=track_status,
            ),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.has_applied",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.mark_applied",
                new_callable=AsyncMock,
            ) as mock_mark,
        ):
            await consumer._process_single(_make_batch())

        assert states == [SourceBatchDuckgresStatus.State.EXECUTING, SourceBatchDuckgresStatus.State.SUCCEEDED]
        mock_mark.assert_called_once()

    @pytest.mark.asyncio
    async def test_final_marker_requires_existing_apply_and_does_not_process(self):
        consumer = _make_consumer()
        consumer._process_batch = AsyncMock()

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.has_applied",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.mark_applied",
                new_callable=AsyncMock,
            ) as mock_mark,
        ):
            await consumer._process_single(_make_batch(is_final_batch=True))

        consumer._process_batch.assert_not_called()
        mock_mark.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_sets_waiting_retry(self):
        consumer = _make_consumer(max_attempts=3)
        consumer._process_batch = AsyncMock(side_effect=ValueError("boom"))
        states: list[str] = []

        async def track_status(conn, *, batch_id, job_state, attempt, error_response=None):
            states.append(job_state)

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.update_status",
                side_effect=track_status,
            ),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.has_applied",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            await consumer._process_single(_make_batch())

        assert states == [SourceBatchDuckgresStatus.State.EXECUTING, SourceBatchDuckgresStatus.State.WAITING_RETRY]

    @pytest.mark.asyncio
    async def test_max_attempts_exceeded_fails_duckgres_run_only(self):
        consumer = _make_consumer(max_attempts=3)

        with patch.object(consumer, "_fail_run", new_callable=AsyncMock) as mock_fail:
            await consumer._process_single(_make_batch(latest_attempt=3))

        mock_fail.assert_called_once()


class TestDuckgresGroupByKey:
    def test_groups_by_team_and_schema(self):
        batches = [
            _make_batch(id="00000000-0000-0000-0000-000000000001", team_id=1, schema_id="a", batch_index=0),
            _make_batch(id="00000000-0000-0000-0000-000000000002", team_id=1, schema_id="b", batch_index=0),
            _make_batch(id="00000000-0000-0000-0000-000000000003", team_id=1, schema_id="a", batch_index=1),
        ]

        groups = _group_by_key(batches)

        assert len(groups) == 2
        assert [batch.batch_index for batch in groups[(1, "a")]] == [0, 1]
