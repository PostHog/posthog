import uuid
from datetime import timedelta

from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized
from temporalio.service import RPCError, RPCStatusCode

from products.data_warehouse.backend.data_load.saved_query_service import (
    delete_saved_query_schedule,
    get_saved_query_schedule,
)


class TestGetSavedQuerySchedule(TestCase):
    def _make_saved_query(self, sync_frequency_interval: timedelta | None = None, timezone: str = "UTC") -> MagicMock:
        sq = MagicMock()
        sq.id = uuid.uuid4()
        sq.team_id = 1
        sq.pk = sq.id
        sq.sync_frequency_interval = sync_frequency_interval
        sq.team.timezone = timezone
        return sq

    def test_uses_calendar_spec(self):
        sq = self._make_saved_query(sync_frequency_interval=timedelta(hours=24))
        schedule = get_saved_query_schedule(sq)
        assert len(schedule.spec.calendars) >= 1

    def test_defaults_to_24h_when_no_interval(self):
        sq = self._make_saved_query(sync_frequency_interval=None)
        schedule = get_saved_query_schedule(sq)
        # 24hr -> medium tier -> 1 hour entry
        assert len(schedule.spec.calendars) == 1
        assert len(schedule.spec.calendars[0].hour) == 1

    def test_passes_team_timezone(self):
        sq = self._make_saved_query(sync_frequency_interval=timedelta(hours=24), timezone="America/New_York")
        schedule = get_saved_query_schedule(sq)
        assert schedule.spec.time_zone_name == "America/New_York"

    @parameterized.expand(
        [
            ("15min", timedelta(minutes=15)),
            ("30min", timedelta(minutes=30)),
            ("1h", timedelta(hours=1)),
            ("6h", timedelta(hours=6)),
            ("12h", timedelta(hours=12)),
            ("24h", timedelta(hours=24)),
            ("7d", timedelta(days=7)),
            ("30d", timedelta(days=30)),
        ]
    )
    def test_deterministic_for_same_id(self, _name, interval):
        sq = self._make_saved_query(sync_frequency_interval=interval)
        schedule_a = get_saved_query_schedule(sq)
        schedule_b = get_saved_query_schedule(sq)
        assert schedule_a.spec.calendars == schedule_b.spec.calendars

    def test_schedule_has_cancel_other_overlap_policy(self):
        sq = self._make_saved_query(sync_frequency_interval=timedelta(hours=6))
        schedule = get_saved_query_schedule(sq)
        from temporalio.client import ScheduleOverlapPolicy

        assert schedule.policy.overlap == ScheduleOverlapPolicy.CANCEL_OTHER

    def test_schedule_action_is_data_modeling_run(self):
        from temporalio.client import ScheduleActionStartWorkflow

        sq = self._make_saved_query(sync_frequency_interval=timedelta(hours=6))
        schedule = get_saved_query_schedule(sq)
        assert isinstance(schedule.action, ScheduleActionStartWorkflow)
        assert schedule.action.workflow == "data-modeling-run"


SAVED_QUERY_SERVICE = "products.data_warehouse.backend.data_load.saved_query_service"


class TestDeleteSavedQuerySchedule(TestCase):
    """`delete_saved_query_schedule` is called from `revert_materialization`'s finally block,
    *after* the DB revert has committed. Transient Temporal transport failures must not
    bubble up as a 500 — they should hand off to a Celery retry task so the user-facing
    DELETE succeeds and the orphaned schedule converges eventually."""

    def setUp(self):
        super().setUp()
        self.saved_query = MagicMock()
        self.saved_query.id = uuid.uuid4()
        self.saved_query.team_id = 42

    def test_swallows_not_found_error(self):
        with (
            patch(f"{SAVED_QUERY_SERVICE}.sync_connect"),
            patch(f"{SAVED_QUERY_SERVICE}.delete_schedule") as mock_delete,
            patch(f"{SAVED_QUERY_SERVICE}.cleanup_orphaned_saved_query_schedule") as mock_task,
        ):
            mock_delete.side_effect = RPCError("not found", RPCStatusCode.NOT_FOUND, b"")

            delete_saved_query_schedule(self.saved_query)

            mock_task.apply_async.assert_not_called()

    @parameterized.expand(
        [
            ("UNAVAILABLE", RPCStatusCode.UNAVAILABLE),
            ("DEADLINE_EXCEEDED", RPCStatusCode.DEADLINE_EXCEEDED),
            ("RESOURCE_EXHAUSTED", RPCStatusCode.RESOURCE_EXHAUSTED),
            ("ABORTED", RPCStatusCode.ABORTED),
            ("INTERNAL", RPCStatusCode.INTERNAL),
            ("UNKNOWN", RPCStatusCode.UNKNOWN),
        ]
    )
    def test_transient_rpc_error_enqueues_retry_and_returns(self, _name, status_code):
        with (
            patch(f"{SAVED_QUERY_SERVICE}.sync_connect"),
            patch(f"{SAVED_QUERY_SERVICE}.delete_schedule") as mock_delete,
            patch(f"{SAVED_QUERY_SERVICE}.cleanup_orphaned_saved_query_schedule") as mock_task,
            patch(f"{SAVED_QUERY_SERVICE}.capture_exception") as mock_capture,
        ):
            rpc_error = RPCError("transient", status_code, b"")
            mock_delete.side_effect = rpc_error

            delete_saved_query_schedule(self.saved_query)

            mock_task.apply_async.assert_called_once_with(args=[str(self.saved_query.id)], countdown=30)
            mock_capture.assert_called_once()

    def test_dns_runtime_error_from_connect_enqueues_retry_and_returns(self):
        with (
            patch(f"{SAVED_QUERY_SERVICE}.sync_connect") as mock_connect,
            patch(f"{SAVED_QUERY_SERVICE}.delete_schedule") as mock_delete,
            patch(f"{SAVED_QUERY_SERVICE}.cleanup_orphaned_saved_query_schedule") as mock_task,
            patch(f"{SAVED_QUERY_SERVICE}.capture_exception") as mock_capture,
        ):
            mock_connect.side_effect = RuntimeError(
                "Failed client connect: tonic::transport::Error(Transport, hyper::Error(Connect, "
                'ConnectError("dns error", Custom { kind: Uncategorized, error: "failed to lookup address"})))'
            )

            delete_saved_query_schedule(self.saved_query)

            mock_delete.assert_not_called()
            mock_task.apply_async.assert_called_once_with(args=[str(self.saved_query.id)], countdown=30)
            mock_capture.assert_called_once()

    def test_non_transient_rpc_error_propagates(self):
        with (
            patch(f"{SAVED_QUERY_SERVICE}.sync_connect"),
            patch(f"{SAVED_QUERY_SERVICE}.delete_schedule") as mock_delete,
            patch(f"{SAVED_QUERY_SERVICE}.cleanup_orphaned_saved_query_schedule") as mock_task,
        ):
            mock_delete.side_effect = RPCError("permission denied", RPCStatusCode.PERMISSION_DENIED, b"")

            with self.assertRaises(RPCError):
                delete_saved_query_schedule(self.saved_query)

            mock_task.apply_async.assert_not_called()

    def test_dispatch_failure_is_captured_not_reraised(self):
        """If queueing the Celery retry itself raises (broker outage), we must still let the
        user-facing DELETE succeed — the orphaned schedule will keep firing until the next
        manual cleanup or reconciliation, but a 500 here is strictly worse than that."""
        with (
            patch(f"{SAVED_QUERY_SERVICE}.sync_connect"),
            patch(f"{SAVED_QUERY_SERVICE}.delete_schedule") as mock_delete,
            patch(f"{SAVED_QUERY_SERVICE}.cleanup_orphaned_saved_query_schedule") as mock_task,
            patch(f"{SAVED_QUERY_SERVICE}.capture_exception") as mock_capture,
        ):
            mock_delete.side_effect = RPCError("transient", RPCStatusCode.UNAVAILABLE, b"")
            mock_task.apply_async.side_effect = RuntimeError("broker down")

            delete_saved_query_schedule(self.saved_query)

            # Both the original transient error and the dispatch failure should be captured.
            self.assertEqual(mock_capture.call_count, 2)
