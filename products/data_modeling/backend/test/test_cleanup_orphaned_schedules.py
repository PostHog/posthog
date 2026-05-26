import uuid

from unittest.mock import patch

from django.test import TestCase

from celery.exceptions import Retry
from parameterized import parameterized
from temporalio.service import RPCError, RPCStatusCode

from products.data_modeling.backend.tasks.cleanup_orphaned_schedules import (
    cleanup_orphaned_saved_query_schedule,
)

TASK_MODULE = "products.data_modeling.backend.tasks.cleanup_orphaned_schedules"


class TestCleanupOrphanedSavedQuerySchedule(TestCase):
    """Async retry path invoked when `delete_saved_query_schedule` hits a transient Temporal
    transport failure. The task must:
      - call `delete_schedule` synchronously on each attempt
      - treat NOT_FOUND as success (idempotent — schedule may already be gone)
      - self.retry on transient transport failures (RuntimeError, RPCError UNAVAILABLE, ...)
      - capture_exception and re-raise once retries are exhausted
    """

    def setUp(self):
        super().setUp()
        self.saved_query_id = str(uuid.uuid4())

    def test_succeeds_when_delete_succeeds(self):
        with (
            patch(f"{TASK_MODULE}.sync_connect"),
            patch(f"{TASK_MODULE}.delete_schedule") as mock_delete,
        ):
            cleanup_orphaned_saved_query_schedule.apply(args=[self.saved_query_id]).get()

            mock_delete.assert_called_once()

    def test_treats_not_found_as_success(self):
        with (
            patch(f"{TASK_MODULE}.sync_connect"),
            patch(f"{TASK_MODULE}.delete_schedule") as mock_delete,
        ):
            mock_delete.side_effect = RPCError("not found", RPCStatusCode.NOT_FOUND, b"")

            # `.get()` would propagate a Retry exception as a failure — if NOT_FOUND were
            # being treated as transient we'd see one here.
            cleanup_orphaned_saved_query_schedule.apply(args=[self.saved_query_id]).get()

    @parameterized.expand(
        [
            ("UNAVAILABLE", RPCError("transient", RPCStatusCode.UNAVAILABLE, b"")),
            ("DEADLINE_EXCEEDED", RPCError("transient", RPCStatusCode.DEADLINE_EXCEEDED, b"")),
            ("RUNTIME_ERROR_DNS", RuntimeError("Failed client connect: dns error")),
        ]
    )
    def test_retries_on_transient_failure(self, _name, exc):
        with (
            patch(f"{TASK_MODULE}.sync_connect"),
            patch(f"{TASK_MODULE}.delete_schedule") as mock_delete,
            patch.object(cleanup_orphaned_saved_query_schedule, "retry", side_effect=Retry()) as mock_retry,
        ):
            mock_delete.side_effect = exc

            with self.assertRaises(Retry):
                cleanup_orphaned_saved_query_schedule.apply(args=[self.saved_query_id], throw=True).get()

            mock_retry.assert_called_once()

    def test_captures_exception_when_retries_exhausted(self):
        with (
            patch(f"{TASK_MODULE}.sync_connect"),
            patch(f"{TASK_MODULE}.delete_schedule") as mock_delete,
            patch.object(
                cleanup_orphaned_saved_query_schedule,
                "retry",
                side_effect=cleanup_orphaned_saved_query_schedule.MaxRetriesExceededError("exhausted"),
            ),
            patch(f"{TASK_MODULE}.capture_exception") as mock_capture,
        ):
            mock_delete.side_effect = RPCError("transient", RPCStatusCode.UNAVAILABLE, b"")

            with self.assertRaises(cleanup_orphaned_saved_query_schedule.MaxRetriesExceededError):
                cleanup_orphaned_saved_query_schedule.apply(args=[self.saved_query_id], throw=True).get()

            mock_capture.assert_called_once()
