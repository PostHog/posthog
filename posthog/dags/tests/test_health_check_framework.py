import pytest

import dagster
from parameterized import parameterized

from posthog.dags.common.health.detectors import (
    batch_detector,
    clickhouse_batch_detector_from_fn,
    resolve_execution_policy,
)
from posthog.dags.common.health.query import _validate_clickhouse_team_query
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
        detector = clickhouse_batch_detector_from_fn(_batch_detect_fn)
        policy = resolve_execution_policy(detector)

        assert policy.batch_size == 250
        assert policy.max_concurrent == 1

    def test_policy_overrides(self):
        detector = clickhouse_batch_detector_from_fn(_batch_detect_fn)
        policy = resolve_execution_policy(detector, batch_size=500, max_concurrent=2)

        assert policy.batch_size == 500
        assert policy.max_concurrent == 2

    @parameterized.expand([("batch_size", 0), ("max_concurrent", 0)])
    def test_policy_rejects_non_positive_values(self, field: str, value: int):
        detector = batch_detector(_batch_detect_fn)
        kwargs = {field: value}

        with pytest.raises(ValueError):
            resolve_execution_policy(detector, **kwargs)


class TestClickhouseQueryValidation:
    def test_validate_clickhouse_query_requires_team_ids_placeholder(self):
        with pytest.raises(ValueError):
            _validate_clickhouse_team_query("SELECT 1 WHERE timestamp >= now() - INTERVAL %(lookback_days)s DAY")

    def test_validate_clickhouse_query_requires_lookback_placeholder(self):
        with pytest.raises(ValueError):
            _validate_clickhouse_team_query("SELECT 1 WHERE team_id IN %(team_ids)s")

    def test_validate_clickhouse_query_accepts_required_placeholders(self):
        _validate_clickhouse_team_query(
            "SELECT 1 WHERE team_id IN %(team_ids)s AND timestamp >= now() - INTERVAL %(lookback_days)s DAY"
        )


class TestTeamRolloutSelection:
    @parameterized.expand(
        [
            ("zero_percent", 0.0, 0),
            ("tiny_percent_rounds_up", 0.01, 1),
            ("fractional_percent_rounds_up", 1.1, 2),
            ("five_percent", 5.0, 5),
            ("full_percent", 100.0, 100),
        ]
    )
    def test_rollout_filtering(self, _name: str, rollout_percentage: float, expected_count: int):
        team_ids = list(range(1, 101))
        selected = _filter_team_ids_for_rollout(team_ids, rollout_percentage)
        assert len(selected) == expected_count

    @parameterized.expand(
        [
            ("negative", -1.0),
            ("over_100", 101.0),
        ]
    )
    def test_rollout_filter_rejects_invalid_percentages(self, _name: str, rollout_percentage: float):
        with pytest.raises(ValueError):
            _filter_team_ids_for_rollout([100], rollout_percentage)

    def test_rollout_is_deterministic(self):
        team_ids = list(range(1, 101))
        first = _filter_team_ids_for_rollout(team_ids, 1.1)
        second = _filter_team_ids_for_rollout(team_ids, 1.1)
        assert first == second
