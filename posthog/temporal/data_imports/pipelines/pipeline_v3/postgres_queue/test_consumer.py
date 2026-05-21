from typing import Any

import pytest
from unittest.mock import AsyncMock, patch

from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer import (
    BatchConsumer,
    ConsumerConfig,
    _group_by_key,
)
from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import PendingBatch

from products.warehouse_sources_queue.backend.models import SourceBatchStatus


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


def _make_consumer(max_attempts: int = 3, **kwargs) -> BatchConsumer:
    config = ConsumerConfig(
        database_url="postgres://unused:unused@localhost/unused",
        max_attempts=max_attempts,
        **kwargs,
    )
    mock_process = AsyncMock()
    consumer = BatchConsumer(config=config, process_batch=mock_process)
    consumer._conn = AsyncMock()
    consumer._recovery_conn = AsyncMock()
    return consumer


class TestProcessSingle:
    @pytest.mark.asyncio
    async def test_success_updates_status_to_executing_then_succeeded(self):
        consumer = _make_consumer()
        batch = _make_batch(latest_attempt=0)
        states: list[str] = []

        async def track_status(conn, *, batch_id, job_state, attempt, error_response=None):
            states.append(job_state)

        consumer._process_batch = AsyncMock()
        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
            side_effect=track_status,
        ):
            await consumer._process_single(batch)

        assert states == [SourceBatchStatus.State.EXECUTING, SourceBatchStatus.State.SUCCEEDED]

    @pytest.mark.asyncio
    async def test_error_sets_waiting_retry(self):
        consumer = _make_consumer(max_attempts=3)
        batch = _make_batch(latest_attempt=0)
        states: list[str] = []

        async def track_status(conn, *, batch_id, job_state, attempt, error_response=None):
            states.append(job_state)

        consumer._process_batch = AsyncMock(side_effect=ValueError("boom"))
        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
            side_effect=track_status,
        ):
            await consumer._process_single(batch)

        assert states == [SourceBatchStatus.State.EXECUTING, SourceBatchStatus.State.WAITING_RETRY]

    @pytest.mark.asyncio
    async def test_max_attempts_exceeded_fails_run(self):
        consumer = _make_consumer(max_attempts=3)
        batch = _make_batch(latest_attempt=3)

        with patch.object(consumer, "_fail_run", new_callable=AsyncMock) as mock_fail:
            await consumer._process_single(batch)

        mock_fail.assert_called_once()
        assert "max retries exceeded" in mock_fail.call_args[1]["reason"]

    @pytest.mark.asyncio
    async def test_error_at_max_attempts_fails_run(self):
        consumer = _make_consumer(max_attempts=2)
        batch = _make_batch(latest_attempt=1)
        consumer._process_batch = AsyncMock(side_effect=RuntimeError("crash"))

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch.object(consumer, "_fail_run", new_callable=AsyncMock) as mock_fail,
        ):
            await consumer._process_single(batch)

        mock_fail.assert_called_once()


class TestProcessGroup:
    @pytest.mark.asyncio
    async def test_processes_batches_in_order(self):
        consumer = _make_consumer()
        order: list[int] = []

        async def track_batch(batch):
            order.append(batch.batch_index)

        consumer._process_batch = track_batch

        batches = [_make_batch(batch_index=i, id=f"00000000-0000-0000-0000-{i + 1:012d}") for i in range(3)]

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ) as mock_unlock,
        ):
            await consumer._process_group((1, "schema-1"), batches)

        assert order == [0, 1, 2]
        mock_unlock.assert_called_once()

    @pytest.mark.asyncio
    async def test_unlocks_even_on_error(self):
        consumer = _make_consumer()
        consumer._process_batch = AsyncMock(side_effect=RuntimeError("crash"))

        batches = [_make_batch()]

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ) as mock_unlock,
            patch.object(consumer, "_fail_run", new_callable=AsyncMock),
        ):
            await consumer._process_group((1, "schema-1"), batches)

        mock_unlock.assert_called_once()

    @pytest.mark.asyncio
    async def test_stops_on_shutdown(self):
        consumer = _make_consumer()
        processed: list[int] = []

        async def track_and_shutdown(batch):
            processed.append(batch.batch_index)
            if batch.batch_index == 0:
                consumer._shutdown.set()

        consumer._process_batch = track_and_shutdown

        batches = [_make_batch(batch_index=i, id=f"00000000-0000-0000-0000-{i + 1:012d}") for i in range(3)]

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ),
        ):
            await consumer._process_group((1, "schema-1"), batches)

        assert processed == [0]


class TestRecoverySweep:
    @pytest.mark.asyncio
    async def test_retries_stale_below_max(self):
        consumer = _make_consumer(max_attempts=3)
        stale_batch = _make_batch(latest_attempt=1)

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_stale_executing",
                new_callable=AsyncMock,
                return_value=[stale_batch],
            ),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ) as mock_status,
        ):
            await consumer._recovery_sweep()

        mock_status.assert_called_once_with(
            consumer._recovery_conn,
            batch_id=stale_batch.id,
            job_state=SourceBatchStatus.State.WAITING_RETRY,
            attempt=1,
        )

    @pytest.mark.asyncio
    async def test_fails_exhausted_stale_batch(self):
        consumer = _make_consumer(max_attempts=3)
        stale_batch = _make_batch(latest_attempt=3)

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_stale_executing",
                new_callable=AsyncMock,
                return_value=[stale_batch],
            ),
            patch.object(consumer, "_fail_run", new_callable=AsyncMock) as mock_fail,
        ):
            await consumer._recovery_sweep()

        mock_fail.assert_called_once()
        assert "max retries exceeded" in mock_fail.call_args[1]["reason"]


class TestGroupByKey:
    def test_groups_by_team_and_schema(self):
        batches = [
            _make_batch(id="00000000-0000-0000-0000-000000000001", team_id=1, schema_id="a", batch_index=0),
            _make_batch(id="00000000-0000-0000-0000-000000000002", team_id=1, schema_id="b", batch_index=0),
            _make_batch(id="00000000-0000-0000-0000-000000000003", team_id=1, schema_id="a", batch_index=1),
            _make_batch(id="00000000-0000-0000-0000-000000000004", team_id=2, schema_id="a", batch_index=0),
        ]

        groups = _group_by_key(batches)

        assert len(groups) == 3
        assert len(groups[(1, "a")]) == 2
        assert len(groups[(1, "b")]) == 1
        assert len(groups[(2, "a")]) == 1

    def test_preserves_insertion_order(self):
        batches = [
            _make_batch(id="00000000-0000-0000-0000-000000000001", team_id=1, schema_id="a", batch_index=0),
            _make_batch(id="00000000-0000-0000-0000-000000000002", team_id=1, schema_id="a", batch_index=1),
            _make_batch(id="00000000-0000-0000-0000-000000000003", team_id=1, schema_id="a", batch_index=2),
        ]

        groups = _group_by_key(batches)

        assert [b.batch_index for b in groups[(1, "a")]] == [0, 1, 2]

    def test_empty_input(self):
        assert _group_by_key([]) == {}
