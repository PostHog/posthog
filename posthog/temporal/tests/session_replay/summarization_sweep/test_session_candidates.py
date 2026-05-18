from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import ClickhouseTestMixin

from posthog.hogql import ast

from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.temporal.session_replay.summarization_sweep.constants import DEFAULT_SAMPLE_RATE, SAMPLE_RATE_PRECISION
from posthog.temporal.session_replay.summarization_sweep.session_candidates import (
    _build_user_defined_query,
    _sampling_having_predicate,
    coerce_sample_rate,
    fetch_recent_session_ids,
)

from products.signals.backend.models import SignalSourceConfig


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, DEFAULT_SAMPLE_RATE),
        (1.0, 1.0),
        (0.0, 0.0),
        (0.25, 0.25),
        ("0.5", 0.5),
        (2, 1.0),  # clamped
        (-0.1, 0.0),  # clamped
        ("nope", DEFAULT_SAMPLE_RATE),
        (float("nan"), DEFAULT_SAMPLE_RATE),
        ([], DEFAULT_SAMPLE_RATE),
        (True, DEFAULT_SAMPLE_RATE),  # bool subclasses int; `float(True) == 1.0` would slip through.
        (False, DEFAULT_SAMPLE_RATE),
    ],
)
def test_coerce_sample_rate(raw, expected):
    assert coerce_sample_rate(raw) == expected


def test_sampling_having_predicate_passthrough_at_full_rate():
    assert _sampling_having_predicate(1.0) is None


def test_sampling_having_predicate_short_circuits_at_zero():
    expr = _sampling_having_predicate(0.0)
    assert isinstance(expr, ast.Constant) and expr.value is False


def test_build_user_defined_query_returns_none_for_empty():
    assert _build_user_defined_query(None) is None
    assert _build_user_defined_query({}) is None
    assert _build_user_defined_query("not a dict") is None  # type: ignore[arg-type]


def test_sampling_having_predicate_builds_modulo_compare():
    expr = _sampling_having_predicate(0.25)
    assert isinstance(expr, ast.CompareOperation)
    assert expr.op == ast.CompareOperationOp.Lt
    assert isinstance(expr.right, ast.Constant)
    assert expr.right.value == int(0.25 * SAMPLE_RATE_PRECISION)
    assert isinstance(expr.left, ast.Call) and expr.left.name == "modulo"
    inner = expr.left.args[0]
    assert isinstance(inner, ast.Call) and inner.name == "cityHash64"


def _enable_source(team) -> None:
    team.organization.is_ai_data_processing_approved = True
    team.organization.save(update_fields=["is_ai_data_processing_approved"])
    SignalSourceConfig.objects.create(
        team=team,
        source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
        source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
        enabled=True,
    )


class TestSamplingPushdown(ClickhouseTestMixin):
    @pytest.mark.django_db(transaction=True)
    def test_full_rate_returns_all(self, team) -> None:
        _enable_source(team)
        sessions = self._produce_sessions(team.id, count=10)

        ids = fetch_recent_session_ids(team=team, lookback_minutes=30, sample_rate=1.0)
        assert sorted(ids) == sorted(sessions)

    @pytest.mark.django_db(transaction=True)
    def test_zero_rate_returns_none(self, team) -> None:
        _enable_source(team)
        self._produce_sessions(team.id, count=10)

        ids = fetch_recent_session_ids(team=team, lookback_minutes=30, sample_rate=0.0)
        assert ids == []

    @pytest.mark.django_db(transaction=True)
    def test_partial_rate_is_stable_across_calls(self, team) -> None:
        _enable_source(team)
        self._produce_sessions(team.id, count=40)

        first = fetch_recent_session_ids(team=team, lookback_minutes=30, sample_rate=0.5)
        second = fetch_recent_session_ids(team=team, lookback_minutes=30, sample_rate=0.5)
        assert first == second
        assert 0 < len(first) < 40

    @staticmethod
    def _produce_sessions(team_id: int, *, count: int) -> list[str]:
        base = datetime.now(UTC) - timedelta(minutes=20)
        session_ids = [f"sweep-test-{team_id}-{i:04x}" for i in range(count)]
        for i, sid in enumerate(session_ids):
            first = base + timedelta(seconds=i)
            produce_replay_summary(
                team_id=team_id,
                session_id=sid,
                first_timestamp=first.isoformat(),
                last_timestamp=(first + timedelta(seconds=120)).isoformat(),
                active_milliseconds=60_000,
            )
        return session_ids
