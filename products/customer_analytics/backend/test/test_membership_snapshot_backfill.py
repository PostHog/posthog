import asyncio
from collections.abc import AsyncGenerator, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID

from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from temporalio.client import WorkflowExecutionStatus
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from products.customer_analytics.backend.facade.membership_snapshot_contracts import (
    MAX_CHECKPOINT_KEY_BYTES,
    MembershipSnapshotBatch,
    MembershipSnapshotCheckpoint,
    MembershipSnapshotInput,
)
from products.customer_analytics.backend.logic.membership_backfill import MembershipRow
from products.customer_analytics.backend.logic.membership_snapshot_backfill import (
    MembershipSnapshotLoader,
    MembershipSnapshotRejectedError,
    get_snapshot_read_settings,
)
from products.customer_analytics.backend.temporal.membership_snapshot_backfill import load_membership_snapshot_activity
from products.data_modeling.backend.facade.contracts import MaterializedQuerySnapshot

CHECKED_AT = datetime(2024, 5, 4, 12, 0, 0, 123456, tzinfo=UTC)
VIEW_ID = "00000000-0000-4000-8000-000000000010"
JOB_ID = "00000000-0000-4000-8000-000000000011"


def create_input(*, dry_run: bool = False, max_rows: int = 7, batch_size: int = 2) -> MembershipSnapshotInput:
    return MembershipSnapshotInput(
        team_id=23,
        group_type_index=1,
        source_view_id=VIEW_ID,
        source_job_id=JOB_ID,
        checked_at=CHECKED_AT,
        expected_rows=7,
        max_rows=max_rows,
        membership_version=17,
        dry_run=dry_run,
        batch_size=batch_size,
    )


def create_rows() -> list[Mapping[str, object]]:
    return [
        {
            "project_id": 23,
            "group_type_index": 1,
            "group_key": group,
            "distinct_id": distinct_id,
            "first_seen": CHECKED_AT - timedelta(days=3),
            "last_seen": CHECKED_AT - timedelta(microseconds=7),
            "eligibility_status": "eligible",
            "checked_at": CHECKED_AT,
        }
        for group, distinct_id in [
            ("account-a", "visitor-01"),
            ("account-a", "visitor-02"),
            ("account-a", "visitor-03"),
            ("account-b", "visitor-01"),
            ("account-b", "visitor-04"),
            ("account-c", "visitor-02"),
            ("account-c", "visitor-05"),
        ]
    ]


def create_batch(input: MembershipSnapshotInput | None = None) -> MembershipSnapshotBatch:
    return MembershipSnapshotBatch(
        input=input or create_input(),
        snapshot=MaterializedQuerySnapshot(
            view_id=UUID(VIEW_ID),
            job_id=UUID(JOB_ID),
            name="example_membership_snapshot",
            revision="snapshot-v1",
            rows_materialized=7,
        ),
    )


class FakeSnapshotBackend:
    def __init__(self, input: MembershipSnapshotInput, rows: Sequence[Mapping[str, object]] | None = None) -> None:
        self.input = input
        self.rows = list(create_rows() if rows is None else rows)
        self.memberships: dict[tuple[str, str], tuple[datetime, datetime]] = {}
        self.fail_after_pairs: int | None = None
        self.source_changed_after_pairs: int | None = None
        self.streams_closed = 0

    async def check_source(self) -> None:
        if self.source_changed_after_pairs is not None and len(self.memberships) >= self.source_changed_after_pairs:
            raise MembershipSnapshotRejectedError("Source changed")

    async def stream_rows(self, checkpoint: MembershipSnapshotCheckpoint) -> AsyncGenerator[Mapping[str, object]]:
        remaining = self.input.max_rows - checkpoint.rows_read
        try:
            for row in self.rows:
                key = (cast(str, row["group_key"]), cast(str, row["distinct_id"]))
                if checkpoint.rows_read and key <= (checkpoint.group_key, checkpoint.distinct_id):
                    continue
                if remaining <= 0:
                    break
                yield row
                remaining -= 1
        finally:
            self.streams_closed += 1

    async def write_rows(self, rows: Sequence[MembershipRow]) -> None:
        for row in rows:
            key = (row.group_key, row.distinct_id)
            previous = self.memberships.get(key)
            self.memberships[key] = (
                min(previous[0], row.first_seen) if previous else row.first_seen,
                max(previous[1], row.last_seen) if previous else row.last_seen,
            )
        if self.fail_after_pairs is not None and len(self.memberships) >= self.fail_after_pairs:
            self.fail_after_pairs = None
            raise ConnectionError("Acknowledgement lost")


class TestMembershipSnapshotLoader(SimpleTestCase):
    @parameterized.expand([(0, "1024"), (512, "512"), (2048, "1024")])
    def test_streaming_read_caps_preserve_stricter_limits_and_encode_booleans(self, memory: int, expected: str) -> None:
        settings = get_snapshot_read_settings(
            {"max_memory_usage": memory, "max_bytes_to_read": 1000, "allow_experimental_object_type": True},
            ceilings={"max_memory_usage": 1024, "max_bytes_to_read": 2000, "max_execution_time": 5},
            timeout=120,
        )
        self.assertEqual(settings["max_memory_usage"], expected)
        self.assertEqual(settings["max_bytes_to_read"], "1000")
        self.assertEqual(settings["max_execution_time"], "5")
        self.assertEqual(settings["allow_experimental_object_type"], "1")
        self.assertEqual(settings["read_overflow_mode"], "throw")
        self.assertEqual(settings["readonly"], "2")

    def test_activity_retries_from_the_last_confirmed_heartbeat(self) -> None:
        batch = create_batch()
        backend = FakeSnapshotBackend(batch.input)
        backend.fail_after_pairs = 4
        client = MagicMock()
        client.get_schedule_handle.return_value.describe = AsyncMock(
            return_value=SimpleNamespace(schedule=SimpleNamespace(state=SimpleNamespace(paused=True)))
        )
        client.get_workflow_handle.return_value.describe = AsyncMock(
            return_value=SimpleNamespace(status=WorkflowExecutionStatus.COMPLETED)
        )
        redis = MagicMock()
        redis.lock.return_value.acquire.return_value = True
        redis.lock.return_value.owned.return_value = True
        environment = ActivityEnvironment()
        with (
            patch(
                "products.customer_analytics.backend.logic.membership_snapshot_backfill.get_redis_client",
                return_value=redis,
            ),
            patch(
                "products.customer_analytics.backend.logic.membership_snapshot_backfill.ClickHouseMembershipSnapshotBackend",
                return_value=backend,
            ),
            patch(
                "products.customer_analytics.backend.temporal.membership_snapshot_backfill.async_connect",
                return_value=client,
            ),
        ):
            with self.assertRaises(ApplicationError) as failure:
                asyncio.run(environment.run(load_membership_snapshot_activity, batch))
            checkpoint = failure.exception.details[0]
            self.assertEqual(checkpoint["rows_read"], 2)
            environment.info = replace(environment.info, attempt=2, heartbeat_details=(checkpoint,))
            step = asyncio.run(environment.run(load_membership_snapshot_activity, batch))
        self.assertEqual(step.checkpoint.rows_read, 7)
        self.assertEqual(step.checkpoint.rows_written, 7)
        self.assertEqual(len(backend.memberships), 7)

    @parameterized.expand([(False, 7), (True, 7), (False, 3)])
    def test_streams_the_approved_rows_with_original_bounds(self, dry_run: bool, max_rows: int) -> None:
        input = create_input(dry_run=dry_run, max_rows=max_rows)
        backend = FakeSnapshotBackend(input)
        checkpoints: list[MembershipSnapshotCheckpoint] = []
        loader = MembershipSnapshotLoader(create_batch(input), backend, deadline=float("inf"))
        result = asyncio.run(loader.run(checkpoints.append))
        self.assertTrue(result.completed)
        self.assertEqual(result.checkpoint.rows_read, max_rows)
        self.assertEqual(result.checkpoint.rows_written, 0 if dry_run else max_rows)
        self.assertEqual(len(backend.memberships), 0 if dry_run else max_rows)
        self.assertEqual(backend.streams_closed, 1)
        if not dry_run:
            for bounds in backend.memberships.values():
                self.assertEqual(bounds, (CHECKED_AT - timedelta(days=3), CHECKED_AT - timedelta(microseconds=7)))

    def test_resumes_after_lost_ack_without_skipping_pairs_or_narrowing_existing_bounds(self) -> None:
        input = create_input()
        backend = FakeSnapshotBackend(input)
        older = CHECKED_AT - timedelta(days=30)
        newer = CHECKED_AT + timedelta(days=30)
        backend.memberships[("account-a", "visitor-01")] = (older, newer)
        backend.fail_after_pairs = 4
        checkpoints = [MembershipSnapshotCheckpoint()]
        loader = MembershipSnapshotLoader(create_batch(input), backend, deadline=float("inf"))
        with self.assertRaises(ConnectionError):
            asyncio.run(loader.run(checkpoints.append))
        self.assertEqual(checkpoints[-1].rows_read, 2)
        resumed = replace(create_batch(input), checkpoint=checkpoints[-1])
        result = asyncio.run(MembershipSnapshotLoader(resumed, backend, deadline=float("inf")).run(checkpoints.append))
        self.assertEqual(result.checkpoint.rows_written, 7)
        self.assertEqual(len(backend.memberships), 7)
        self.assertEqual(backend.memberships[("account-a", "visitor-01")], (older, newer))
        self.assertIn(("account-b", "visitor-01"), backend.memberships)

    @parameterized.expand(
        [
            ("project_id", 24),
            ("group_type_index", 0),
            ("eligibility_status", "anonymous"),
            ("checked_at", CHECKED_AT + timedelta(microseconds=1)),
            ("group_key", ""),
            ("distinct_id", ""),
            ("first_seen", CHECKED_AT + timedelta(days=1)),
            ("last_seen", "2024-05-04"),
            ("group_key", "k" * (MAX_CHECKPOINT_KEY_BYTES + 1)),
            ("group_type_index", True),
        ]
    )
    def test_rejects_invalid_source_rows_before_writing(self, field: str, value: object) -> None:
        rows = create_rows()
        rows[0] = {**rows[0], field: value}
        backend = FakeSnapshotBackend(create_input(), rows)
        with self.assertRaises(MembershipSnapshotRejectedError):
            asyncio.run(MembershipSnapshotLoader(create_batch(), backend, deadline=float("inf")).run(lambda _: None))
        self.assertEqual(backend.memberships, {})

    def test_stops_before_another_batch_when_the_snapshot_changes(self) -> None:
        backend = FakeSnapshotBackend(create_input())
        backend.source_changed_after_pairs = 2
        checkpoints = [MembershipSnapshotCheckpoint()]
        with self.assertRaises(MembershipSnapshotRejectedError):
            asyncio.run(
                MembershipSnapshotLoader(create_batch(), backend, deadline=float("inf")).run(checkpoints.append)
            )
        self.assertEqual(checkpoints[-1].rows_written, 2)
        self.assertEqual(len(backend.memberships), 2)
        self.assertEqual(backend.streams_closed, 1)

    @parameterized.expand([(True,), (False,)])
    def test_rejects_duplicate_and_out_of_order_keys(self, duplicate: bool) -> None:
        rows = create_rows()
        rows[1] = rows[0] if duplicate else {**rows[1], "group_key": "account-0"}
        backend = FakeSnapshotBackend(create_input(), rows)
        with self.assertRaises(MembershipSnapshotRejectedError):
            asyncio.run(MembershipSnapshotLoader(create_batch(), backend, deadline=float("inf")).run(lambda _: None))
        self.assertEqual(backend.memberships, {})

    def test_does_not_mark_a_truncated_source_complete(self) -> None:
        backend = FakeSnapshotBackend(create_input(), create_rows()[:-1])
        checkpoints: list[MembershipSnapshotCheckpoint] = []
        with self.assertRaises(MembershipSnapshotRejectedError):
            asyncio.run(
                MembershipSnapshotLoader(create_batch(), backend, deadline=float("inf")).run(checkpoints.append)
            )
        self.assertEqual(checkpoints[-1].rows_read, 6)

    def test_closes_the_stream_after_a_bounded_slice(self) -> None:
        backend = FakeSnapshotBackend(create_input())
        checkpoints: list[MembershipSnapshotCheckpoint] = []
        with patch("products.customer_analytics.backend.logic.membership_snapshot_backfill.monotonic", return_value=1):
            step = asyncio.run(MembershipSnapshotLoader(create_batch(), backend, deadline=10).run(checkpoints.append))
        self.assertFalse(step.completed)
        self.assertEqual(step.checkpoint.rows_read, 2)
        self.assertEqual(backend.streams_closed, 1)
