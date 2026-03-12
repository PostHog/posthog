from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.llm_analytics.coordinator_metrics import (
    increment_team_failed,
    increment_team_succeeded,
    record_teams_discovered,
)


class TestCoordinatorMetrics:
    @parameterized.expand(
        [
            ("record_teams_discovered", record_teams_discovered, [5, "clustering", "trace"]),
            ("increment_team_succeeded", increment_team_succeeded, ["clustering", "trace"]),
            ("increment_team_failed", increment_team_failed, ["clustering", "trace"]),
            ("record_teams_discovered_summarization", record_teams_discovered, [10, "summarization", "generation"]),
            ("increment_team_succeeded_summarization", increment_team_succeeded, ["summarization", "generation"]),
            ("increment_team_failed_summarization", increment_team_failed, ["summarization", "generation"]),
        ]
    )
    def test_counter_emits_in_temporal_context(self, _name, fn, args):
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter

        with patch(
            "posthog.temporal.llm_analytics.coordinator_metrics.get_metric_meter",
            return_value=mock_meter,
        ):
            fn(*args)

        mock_counter.add.assert_called_once()
