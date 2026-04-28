from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.session_replay.delete_recordings.metrics import (
    DELETE_RECORDINGS_ACTIVITY_TYPES,
    DELETE_RECORDINGS_WORKFLOW_TYPES,
    DeleteRecordingsMetricsInterceptor,
    increment_recordings_deleted,
    increment_recordings_failed,
)


class TestTypesSets:
    @parameterized.expand(
        [
            ("load-recordings-with-person",),
            ("load-recordings-with-team-id",),
            ("load-recordings-with-query",),
            ("load-session-id-chunk",),
            ("cleanup-session-id-chunks",),
            ("delete-recordings",),
            ("purge-deleted-metadata",),
        ]
    )
    def test_activity_types(self, activity_type):
        assert activity_type in DELETE_RECORDINGS_ACTIVITY_TYPES

    @parameterized.expand(
        [
            ("delete-recordings-with-person",),
            ("delete-recordings-with-team",),
            ("delete-recordings-with-query",),
            ("delete-recordings-with-session-ids",),
            ("purge-deleted-recording-metadata",),
        ]
    )
    def test_workflow_types(self, workflow_type):
        assert workflow_type in DELETE_RECORDINGS_WORKFLOW_TYPES


class TestCounterHelpers:
    @parameterized.expand(
        [
            ("deleted", increment_recordings_deleted, 5),
            ("failed", increment_recordings_failed, 3),
        ]
    )
    def test_counter_emits_in_temporal_context(self, _name, fn, count):
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter

        with patch(
            "posthog.temporal.session_replay.delete_recordings.metrics.get_metric_meter",
            return_value=mock_meter,
        ):
            fn(count)

        mock_counter.add.assert_called_once_with(count)

    @parameterized.expand(
        [
            ("deleted_zero", increment_recordings_deleted, 0),
            ("deleted_negative", increment_recordings_deleted, -1),
            ("failed_zero", increment_recordings_failed, 0),
            ("failed_negative", increment_recordings_failed, -1),
        ]
    )
    def test_counter_noops_for_non_positive(self, _name, fn, count):
        with patch(
            "posthog.temporal.session_replay.delete_recordings.metrics.get_metric_meter",
        ) as mock_get_meter:
            fn(count)
            mock_get_meter.assert_not_called()


class TestInterceptorStructure:
    def test_creates_activity_interceptor(self):
        interceptor = DeleteRecordingsMetricsInterceptor()
        result = interceptor.intercept_activity(MagicMock())
        assert result is not None

    def test_returns_workflow_interceptor_class(self):
        interceptor = DeleteRecordingsMetricsInterceptor()
        result = interceptor.workflow_interceptor_class(MagicMock())
        assert result is not None
