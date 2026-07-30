from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from clickhouse_driver.errors import ServerException, SocketTimeoutError

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError

from posthog.errors import wrap_clickhouse_query_error
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.temporal.session_replay.summarization_sweep.constants import DEFAULT_SAMPLE_RATE, SAMPLE_RATE_PRECISION
from posthog.temporal.session_replay.summarization_sweep.session_candidates import (
    _build_user_defined_query,
    _sampling_having_predicate,
    coerce_sample_rate,
    fetch_recent_session_ids,
    filter_session_ids_with_events,
    is_transient_clickhouse_error,
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
    @pytest.mark.django_db
    def test_full_rate_returns_all(self, team) -> None:
        _enable_source(team)
        sessions = self._produce_sessions(team.id, count=10)

        ids = fetch_recent_session_ids(team=team, lookback_minutes=30, sample_rate=1.0)
        assert sorted(ids) == sorted(sessions)

    @pytest.mark.django_db
    def test_zero_rate_returns_none(self, team) -> None:
        _enable_source(team)
        self._produce_sessions(team.id, count=10)

        ids = fetch_recent_session_ids(team=team, lookback_minutes=30, sample_rate=0.0)
        assert ids == []

    @pytest.mark.django_db
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


def _ch_error(code: int, message: str = "DB::Exception: boom") -> Exception:
    return wrap_clickhouse_query_error(ServerException(message, code=code))


@pytest.mark.parametrize(
    "exc,transient",
    [
        (_ch_error(394), True),  # QUERY_WAS_CANCELLED — the reported issue
        (_ch_error(735), True),  # QUERY_WAS_CANCELLED_BY_CLIENT
        (_ch_error(236), True),  # ABORTED
        (_ch_error(202), True),  # TOO_MANY_SIMULTANEOUS_QUERIES, wrapped as ClickHouseAtCapacity
        (_ch_error(159), True),  # TIMEOUT_EXCEEDED
        (_ch_error(241, "DB::Exception: Memory limit (total) exceeded"), True),
        (_ch_error(241, "DB::Exception: Memory limit (for query) exceeded"), True),
        (_ch_error(209), True),  # SOCKET_TIMEOUT
        (_ch_error(210), True),  # NETWORK_ERROR
        (SocketTimeoutError(), True),
        (_ch_error(10), False),  # NOT_FOUND_COLUMN_IN_BLOCK — a genuine query bug
        (_ch_error(47), False),  # UNKNOWN_IDENTIFIER
        (ExposedHogQLError("bad query"), False),
        (ValueError("unrelated"), False),
    ],
)
def test_is_transient_clickhouse_error(exc, transient) -> None:
    assert is_transient_clickhouse_error(exc) is transient


def test_fetch_recent_session_ids_skips_tick_when_clickhouse_sheds_the_query() -> None:
    with patch(
        "posthog.temporal.session_replay.summarization_sweep.session_candidates.SessionRecordingListFromQuery",
        side_effect=_ch_error(394),
    ):
        assert fetch_recent_session_ids(team=MagicMock(), lookback_minutes=30) == []


def test_fetch_recent_session_ids_reraises_query_bugs() -> None:
    with patch(
        "posthog.temporal.session_replay.summarization_sweep.session_candidates.SessionRecordingListFromQuery",
        side_effect=_ch_error(10),
    ):
        with pytest.raises(Exception, match="boom"):
            fetch_recent_session_ids(team=MagicMock(), lookback_minutes=30)


def test_filter_session_ids_with_events_skips_tick_when_clickhouse_sheds_the_query() -> None:
    with patch(
        "posthog.temporal.session_replay.summarization_sweep.session_candidates.HogQLQueryRunner",
        side_effect=_ch_error(394),
    ):
        assert filter_session_ids_with_events(team=MagicMock(), session_ids=["a"], lookback_minutes=30) == set()


def test_filter_session_ids_with_events_reraises_query_bugs() -> None:
    with patch(
        "posthog.temporal.session_replay.summarization_sweep.session_candidates.HogQLQueryRunner",
        side_effect=_ch_error(10),
    ):
        with pytest.raises(Exception, match="boom"):
            filter_session_ids_with_events(team=MagicMock(), session_ids=["a"], lookback_minutes=30)
