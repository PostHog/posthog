import pytest
from unittest.mock import MagicMock, patch

import dagster
from parameterized import parameterized

from posthog.dags.common.health.detectors import (
    CLICKHOUSE_BATCH_EXECUTION_POLICY,
    batch_detector,
    resolve_execution_policy,
)
from posthog.dags.common.health.processing import _process_batch_detection
from posthog.dags.common.health.types import HealthCheckResult
from posthog.dags.common.ops import _filter_team_ids_for_rollout
from posthog.models.health_issue import HealthIssue


def _batch_detect_fn(team_ids: list[int], context: dagster.OpExecutionContext) -> dict[int, list[HealthCheckResult]]:
    if not team_ids:
        return {}
    return {
        team_ids[0]: [
            HealthCheckResult(
                severity=HealthIssue.Severity.INFO,
                payload={"ok": True},
            )
        ]
    }


class TestHealthExecutionPolicies:
    def test_default_policy_for_generic_detector(self):
        detector = batch_detector(_batch_detect_fn)
        policy = resolve_execution_policy(detector)

        assert policy.batch_size == 1000
        assert policy.max_concurrent == 5

    def test_default_policy_for_clickhouse_detector(self):
        detector = batch_detector(_batch_detect_fn, **CLICKHOUSE_BATCH_EXECUTION_POLICY)
        policy = resolve_execution_policy(detector)

        assert policy.batch_size == 250
        assert policy.max_concurrent == 1

    def test_policy_overrides(self):
        detector = batch_detector(_batch_detect_fn, **CLICKHOUSE_BATCH_EXECUTION_POLICY)
        policy = resolve_execution_policy(detector, batch_size=500, max_concurrent=2)

        assert policy.batch_size == 500
        assert policy.max_concurrent == 2

    @parameterized.expand([("batch_size", 0), ("max_concurrent", 0)])
    def test_policy_rejects_non_positive_values(self, field: str, value: int):
        detector = batch_detector(_batch_detect_fn)
        kwargs = {field: value}

        with pytest.raises(ValueError):
            resolve_execution_policy(detector, **kwargs)


class TestTeamRolloutSelection:
    @parameterized.expand(
        [
            ("zero", 0.0, 0),
            ("tiny_rounds_up", 0.001, 1),
            ("one_percent", 0.01, 1),
            ("five_percent", 0.05, 5),
            ("full", 1.0, 100),
        ]
    )
    def test_rollout_filtering(self, _name: str, rollout_percentage: float, expected_count: int):
        team_ids = list(range(1, 101))
        selected = _filter_team_ids_for_rollout(team_ids, rollout_percentage)
        assert len(selected) == expected_count

    @parameterized.expand(
        [
            ("negative", -1.0),
            ("over_one", 1.1),
        ]
    )
    def test_rollout_filter_rejects_invalid_percentages(self, _name: str, rollout_percentage: float):
        with pytest.raises(ValueError):
            _filter_team_ids_for_rollout([100], rollout_percentage)

    def test_rollout_is_deterministic(self):
        team_ids = list(range(1, 101))
        first = _filter_team_ids_for_rollout(team_ids, 0.05)
        second = _filter_team_ids_for_rollout(team_ids, 0.05)
        assert first == second


class TestDryRun:
    @patch("posthog.dags.common.health.processing._resolve_stale_issues")
    @patch("posthog.dags.common.health.processing._upsert_issues")
    def test_batch_dry_run_skips_db_writes(self, mock_upsert: MagicMock, mock_resolve: MagicMock):
        context = MagicMock(spec=dagster.OpExecutionContext)
        result = _process_batch_detection([1, 2], "test_kind", _batch_detect_fn, context, dry_run=True)

        mock_upsert.assert_not_called()
        mock_resolve.assert_not_called()
        assert result.teams_with_issues == 1
        assert result.teams_healthy == 1
        assert result.issues_upserted == 0
        assert result.issues_resolved == 0
