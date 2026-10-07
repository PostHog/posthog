import pytest
from unittest.mock import patch

from posthog.temporal.experiments.workflows import _record_publish_outcome


@pytest.mark.parametrize(
    "succeeded,recalculations_synced,expected_status",
    [(2, 2, "published"), (2, 0, "missing"), (0, 0, None)],
)
def test_publish_outcome_counter_separates_published_from_missing(
    succeeded: int, recalculations_synced: int, expected_status: str | None
) -> None:
    """The "missing" emission marks a run that computed results users never see. A flipped condition
    loses that signal; emitting on runs that computed nothing fills it with false positives."""
    with (
        patch("temporalio.workflow.metric_meter") as mock_meter,
        patch("temporalio.workflow.info") as mock_info,
    ):
        mock_info.return_value.workflow_type = "experiment-saved-metrics-workflow"
        _record_publish_outcome(succeeded, recalculations_synced)

    if expected_status is None:
        mock_meter.assert_not_called()
        return
    with_attributes = mock_meter.return_value.with_additional_attributes
    with_attributes.assert_called_once_with(
        {"workflow_type": "experiment-saved-metrics-workflow", "status": expected_status}
    )
    with_attributes.return_value.create_counter.return_value.add.assert_called_once_with(1)
