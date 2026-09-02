from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.session_replay.rasterize_recording.activities.record_failure import record_rasterization_failure
from posthog.temporal.session_replay.rasterize_recording.types import RecordRasterizationFailureInput

from products.exports.backend.tasks.failure_handler import (
    FAILURE_TYPE_OTHER,
    FAILURE_TYPE_RENDERER_UNKNOWN,
    FAILURE_TYPE_SYSTEM,
    FAILURE_TYPE_TIMEOUT_GENERATION,
    FAILURE_TYPE_UNKNOWN,
    FAILURE_TYPE_USER,
)

_MODULE = "posthog.temporal.session_replay.rasterize_recording.activities.record_failure"


def _make_asset(exception: str | None = None) -> MagicMock:
    asset = MagicMock()
    asset.id = 42
    asset.exception = exception
    asset.save = MagicMock()
    return asset


def _run(asset: MagicMock, error_code: str = "TIMEOUT", error_message: str = "render timed out"):
    mock_qs = MagicMock()
    mock_qs.select_related.return_value.get.return_value = asset

    with (
        patch(f"{_MODULE}.ExportedAsset.objects", mock_qs),
        patch(f"{_MODULE}.close_old_connections"),
        patch(f"{_MODULE}.report_export_event") as reporter,
    ):
        record_rasterization_failure(
            RecordRasterizationFailureInput(
                exported_asset_id=42,
                error_code=error_code,
                error_message=error_message,
            )
        )
    return reporter


class TestRecordRasterizationFailure:
    @parameterized.expand(
        [
            ("timeout", "TIMEOUT", FAILURE_TYPE_TIMEOUT_GENERATION),
            ("compositor_deadlock", "BEGINFRAME_DEADLOCK", FAILURE_TYPE_TIMEOUT_GENERATION),
            ("no_snapshots", "NO_SNAPSHOTS", FAILURE_TYPE_USER),
            ("upload_failed", "S3_UPLOAD_UNDECODABLE_RESPONSE", FAILURE_TYPE_SYSTEM),
            ("target_closed", "TARGET_CLOSED", FAILURE_TYPE_SYSTEM),
            ("worker_death_timeout", "ACTIVITY_TIMEOUT", FAILURE_TYPE_TIMEOUT_GENERATION),
            # The renderer's catch-alls have their own buckets so they can't hide in "unknown".
            ("renderer_crash", "UNKNOWN", FAILURE_TYPE_RENDERER_UNKNOWN),
            ("unrecognized_browser_code", "OTHER", FAILURE_TYPE_OTHER),
            # An unmapped code must land in "unknown" rather than being absorbed into a real bucket,
            # so a code the rasterizer adds later shows up as needing classification.
            ("unrecognized", "SOMETHING_NEW", FAILURE_TYPE_UNKNOWN),
        ]
    )
    def test_persists_the_renderers_code_and_its_classification(self, _name, error_code, expected_failure_type):
        asset = _make_asset()

        _run(asset, error_code=error_code)

        assert asset.exception_type == error_code
        assert asset.failure_type == expected_failure_type
        asset.save.assert_called_once_with(update_fields=["exception", "exception_type", "failure_type"])

    def test_records_a_message_for_the_user_not_the_raw_error(self):
        """`exception` is rendered in the export UI, so it carries guidance and the raw text goes to
        the event and the log instead."""
        asset = _make_asset()

        reporter = _run(asset, error_code="NO_SNAPSHOTS", error_message="[NO_SNAPSHOTS] no events for session")

        assert asset.exception == "This recording has no playable data, so there is nothing to export."
        assert reporter.call_args.kwargs["error"] == "[NO_SNAPSHOTS] no events for session"

    def test_keeps_an_already_recorded_reason(self):
        """The sweep and a later retry both reach this activity, and neither saw the actual failure."""
        asset = _make_asset(exception="already recorded")

        reporter = _run(asset)

        asset.save.assert_not_called()
        reporter.assert_not_called()
