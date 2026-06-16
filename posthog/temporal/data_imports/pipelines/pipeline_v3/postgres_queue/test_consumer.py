import asyncio
from typing import Any

import pytest
from unittest.mock import AsyncMock, patch

import psycopg
import structlog

from posthog.temporal.data_imports.pipelines.pipeline_v3.load.health import HealthState
from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer import (
    BatchConsumer,
    ConsumerConfig,
    _group_by_key,
)
from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import FailedRunRef, PendingBatch

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


def _make_failed_run_ref(**overrides: Any) -> FailedRunRef:
    defaults: dict[str, Any] = {
        "run_uuid": "run-1",
        "job_id": "job-1",
        "team_id": 1,
        "schema_id": "schema-1",
        "workflow_run_id": "wf-1",
        "reason": "max retries exceeded: the connection is closed",
    }
    defaults.update(overrides)
    return FailedRunRef(**defaults)


def _make_consumer(max_attempts: int = 3, **kwargs) -> BatchConsumer:
    config = ConsumerConfig(
        database_url="postgres://unused:unused@localhost/unused",
        max_attempts=max_attempts,
        **kwargs,
    )
    mock_process = AsyncMock()
    consumer = BatchConsumer(config=config, process_batch=mock_process)
    consumer._conn = _make_healthy_conn()
    consumer._recovery_conn = _make_healthy_conn()
    return consumer


def _make_healthy_conn(closed: bool = False, broken: bool = False) -> AsyncMock:
    # closed/broken must be real booleans, otherwise _ensure_*_conn sees a dead conn and dials the fake database_url.
    conn = AsyncMock()
    conn.closed = closed
    conn.broken = broken
    return conn


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
    async def test_halts_group_when_batch_does_not_succeed(self):
        consumer = _make_consumer(max_attempts=3)
        processed: list[int] = []

        async def fail_on_one(batch):
            processed.append(batch.batch_index)
            if batch.batch_index == 1:
                raise RuntimeError("boom")

        consumer._process_batch = fail_on_one

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

        # batch 2 must not be processed once batch 1 enters waiting_retry
        assert processed == [0, 1]

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
            error_response={"error": "executing timed out — pod restart or OOM"},
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


class TestFailRun:
    @pytest.mark.asyncio
    async def test_does_not_raise_when_job_status_update_fails(self):
        # A dropped app-DB connection while marking the job Failed must not propagate out of _fail_run.
        consumer = _make_consumer()
        batch = _make_batch()

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.fail_run",
                new_callable=AsyncMock,
            ) as mock_fail_run,
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer._update_job_status_to_failed",
                side_effect=Exception("the connection is closed"),
            ),
        ):
            await consumer._fail_run(batch, reason="max retries exceeded: the connection is closed")

        mock_fail_run.assert_called_once()  # queue batches still marked failed

    @pytest.mark.asyncio
    async def test_attempts_job_status_update_even_when_queue_update_fails(self):
        consumer = _make_consumer()
        batch = _make_batch()

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.fail_run",
                new_callable=AsyncMock,
                side_effect=Exception("the connection is closed"),
            ),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer._update_job_status_to_failed",
            ) as mock_status,
        ):
            await consumer._fail_run(batch, reason="boom")

        mock_status.assert_called_once()


class TestReconcileFailedRuns:
    @pytest.mark.asyncio
    async def test_marks_non_terminal_run_failed(self):
        consumer = _make_consumer()
        ref = _make_failed_run_ref()

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_failed_runs",
                new_callable=AsyncMock,
                return_value=[ref],
            ),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer._mark_job_failed_if_not_terminal",
                return_value=True,
            ) as mock_mark,
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.release_v3_pipeline_lock",
            ) as mock_release,
        ):
            await consumer._reconcile_failed_runs()

        mock_mark.assert_called_once_with(job_id=ref.job_id, team_id=ref.team_id, error=ref.reason)
        mock_release.assert_called_once_with(team_id=ref.team_id, schema_id=ref.schema_id, token=ref.workflow_run_id)

    @pytest.mark.asyncio
    async def test_skips_already_terminal_run(self):
        consumer = _make_consumer()
        ref = _make_failed_run_ref()

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_failed_runs",
                new_callable=AsyncMock,
                return_value=[ref],
            ),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer._mark_job_failed_if_not_terminal",
                return_value=False,
            ) as mock_mark,
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.release_v3_pipeline_lock",
            ) as mock_release,
        ):
            await consumer._reconcile_failed_runs()

        mock_mark.assert_called_once()  # no-op for an already-terminal job, no error
        mock_release.assert_not_called()  # don't release the lock for a job we didn't reconcile

    @pytest.mark.asyncio
    async def test_continues_after_error_on_one_ref(self):
        consumer = _make_consumer()
        ref_a = _make_failed_run_ref(run_uuid="run-a", job_id="job-a")
        ref_b = _make_failed_run_ref(run_uuid="run-b", job_id="job-b")

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_failed_runs",
                new_callable=AsyncMock,
                return_value=[ref_a, ref_b],
            ),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer._mark_job_failed_if_not_terminal",
                side_effect=[Exception("db down"), True],
            ) as mock_mark,
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.release_v3_pipeline_lock",
            ),
        ):
            await consumer._reconcile_failed_runs()

        assert mock_mark.call_count == 2  # error on the first ref does not abort the sweep


class TestConnectionRecovery:
    @pytest.mark.parametrize(
        "closed, broken, expect_reconnect",
        [
            (False, False, False),
            (True, False, True),
            (False, True, True),
        ],
        ids=["healthy", "closed", "broken"],
    )
    @pytest.mark.asyncio
    async def test_ensure_main_conn_reconnects_only_when_dead(self, closed, broken, expect_reconnect):
        consumer = _make_consumer()
        original = _make_healthy_conn(closed=closed, broken=broken)
        consumer._conn = original
        fresh = _make_healthy_conn()

        with patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=fresh) as mock_connect:
            conn = await consumer._ensure_main_conn()

        if expect_reconnect:
            mock_connect.assert_awaited_once()
            assert conn is fresh
        else:
            mock_connect.assert_not_awaited()
            assert conn is original

    @pytest.mark.asyncio
    async def test_concurrent_ensure_main_conn_dials_only_once(self):
        # All concurrent groups hitting a dead conn must share one reconnect, not dial N connections.
        consumer = _make_consumer()
        consumer._conn = _make_healthy_conn(closed=True)
        fresh = _make_healthy_conn()

        async def slow_connect() -> AsyncMock:
            await asyncio.sleep(0)  # yield so the other coroutines reach the check while we're "dialing"
            return fresh

        with patch.object(consumer, "_connect", side_effect=slow_connect) as mock_connect:
            conns = await asyncio.gather(*[consumer._ensure_main_conn() for _ in range(5)])

        assert mock_connect.call_count == 1
        assert all(conn is fresh for conn in conns)

    @pytest.mark.asyncio
    async def test_ensure_recovery_conn_reconnects_when_dead(self):
        consumer = _make_consumer()
        consumer._recovery_conn = _make_healthy_conn(closed=True)
        fresh = _make_healthy_conn()

        with patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=fresh) as mock_connect:
            conn = await consumer._ensure_recovery_conn()

        mock_connect.assert_awaited_once()
        assert conn is fresh

    @pytest.mark.asyncio
    async def test_process_group_does_not_raise_when_unlock_fails(self):
        # An unlock failure must not crash the gather() running every concurrent group.
        consumer = _make_consumer()
        consumer._process_batch = AsyncMock()

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
                side_effect=Exception("the connection is closed"),
            ),
        ):
            await consumer._process_group((1, "schema-1"), [_make_batch()])

    @pytest.mark.asyncio
    async def test_process_group_does_not_raise_when_process_single_raises(self):
        # An unguarded queue-DB write blowing up mid-batch must cost the group, not crash the gather()/pod.
        consumer = _make_consumer()

        with (
            patch.object(
                consumer,
                "_process_single",
                new_callable=AsyncMock,
                side_effect=psycopg.OperationalError("the connection is closed"),
            ) as mock_single,
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ) as mock_unlock,
        ):
            await consumer._process_group((1, "schema-1"), [_make_batch(), _make_batch(batch_index=1)])

        mock_single.assert_awaited_once()  # group halts after the failed batch
        mock_unlock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recovery_sweep_uses_reconnected_conn(self):
        consumer = _make_consumer()
        consumer._recovery_conn = _make_healthy_conn(closed=True)
        fresh = _make_healthy_conn()

        with (
            patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=fresh),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_stale_executing",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_get_stale,
        ):
            await consumer._recovery_sweep()

        mock_get_stale.assert_awaited_once()
        assert mock_get_stale.call_args[0][0] is fresh


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


class TestLogContextBinding:
    """Verify the consumer binds the structlog contextvars `LogMessagesRenderer` needs.

    The CDC Syncs UI panel queries log_entries by `(log_source='external_data_jobs',
    log_source_id=schema_id, instance_id=workflow_run_id)`. The renderer in
    `posthog.temporal.common.logger` reads these from the structlog event_dict, so they
    must be bound via contextvars BEFORE downstream loggers fire.
    """

    @pytest.mark.asyncio
    async def test_process_single_binds_log_context_for_syncs_panel(self):
        consumer = _make_consumer()
        batch = _make_batch(
            latest_attempt=0,
            metadata={"workflow_id": "cdc-extraction-source-123", "workflow_run_id": "wf-run-id-456"},
        )
        seen: dict[str, Any] = {}

        async def capture_context(b):
            seen.update(structlog.contextvars.get_contextvars())

        consumer._process_batch = capture_context

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
            new_callable=AsyncMock,
        ):
            await consumer._process_single(batch)

        assert seen.get("workflow_type") == "cdc-extraction"
        assert seen.get("workflow_id") == "cdc-extraction-source-123"
        assert seen.get("workflow_run_id") == "wf-run-id-456"
        assert seen.get("team_id") == batch.team_id
        assert seen.get("log_source_id") == batch.schema_id
        assert seen.get("external_data_schema_id") == batch.schema_id
        assert seen.get("attempt") == 1

        # Cleared after the batch returns so context doesn't leak across batches.
        assert structlog.contextvars.get_contextvars().get("batch_id") is None

    @pytest.mark.asyncio
    async def test_process_single_binds_external_data_job_workflow_type_for_non_cdc(self):
        """Consumer also runs non-CDC syncs (`external-data-job` workflow_id prefix)."""
        consumer = _make_consumer()
        batch = _make_batch(
            latest_attempt=0,
            metadata={
                "workflow_id": "019df430-765a-0000-0523-040f9c48be64-2026-05-21T00:00:00",
                "workflow_run_id": "wf-run",
            },
        )
        seen: dict[str, Any] = {}

        async def capture_context(b):
            seen.update(structlog.contextvars.get_contextvars())

        consumer._process_batch = capture_context

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
            new_callable=AsyncMock,
        ):
            await consumer._process_single(batch)

        assert seen.get("workflow_type") == "external-data-job"

    @pytest.mark.asyncio
    async def test_process_single_handles_missing_workflow_ids_in_metadata(self):
        """Old batches enqueued before this change have no workflow ids in metadata — must not crash."""
        consumer = _make_consumer()
        consumer._process_batch = AsyncMock()

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
            new_callable=AsyncMock,
        ):
            await consumer._process_single(_make_batch(latest_attempt=0, metadata={}))

        consumer._process_batch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_single_clears_context_on_error(self):
        consumer = _make_consumer(max_attempts=3)
        consumer._process_batch = AsyncMock(side_effect=ValueError("boom"))

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
            new_callable=AsyncMock,
        ):
            await consumer._process_single(_make_batch(latest_attempt=0))

        assert "batch_id" not in structlog.contextvars.get_contextvars()
        assert "workflow_run_id" not in structlog.contextvars.get_contextvars()


class TestHeartbeatLoop:
    @pytest.mark.asyncio
    async def test_reports_until_shutdown(self):
        consumer = _make_consumer(heartbeat_interval_seconds=0.01)
        calls = 0

        def reporter():
            nonlocal calls
            calls += 1

        consumer._health_reporter = reporter

        task = asyncio.create_task(consumer._heartbeat_loop())
        await asyncio.sleep(0.05)
        consumer._shutdown.set()
        await asyncio.wait_for(task, timeout=1.0)

        assert calls >= 2

    @pytest.mark.asyncio
    async def test_keeps_liveness_healthy_through_long_batch(self):
        # A poll cycle (large final-batch compaction) can run far longer than the
        # health timeout; the dedicated heartbeat must keep liveness green so
        # kubelet doesn't SIGTERM the pod mid-batch.
        health = HealthState(timeout_seconds=0.1)
        consumer = _make_consumer(heartbeat_interval_seconds=0.02)
        consumer._health_reporter = health.report_healthy

        task = asyncio.create_task(consumer._heartbeat_loop())
        await asyncio.sleep(0.3)  # simulate a batch ~3x the health timeout
        assert health.is_healthy() is True

        consumer._shutdown.set()
        await asyncio.wait_for(task, timeout=1.0)

        # Once the heartbeat stops, liveness correctly goes stale again.
        await asyncio.sleep(0.2)
        assert health.is_healthy() is False
