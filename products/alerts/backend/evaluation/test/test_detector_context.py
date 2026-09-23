from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import numpy as np

from posthog.models.team import Team
from posthog.models.user import User

from products.alerts.backend.evaluation.contract import ComparableSeries, ExtractionResult, SeriesPoint
from products.alerts.backend.evaluation.detector import evaluate_with_detector
from products.alerts.backend.judge import JudgeAttribution, LLMDetectorMisconfiguredError, SeriesContext, SeriesJudgment

TRENDS_QUERY = {
    "kind": "InsightVizNode",
    "source": {
        "kind": "TrendsQuery",
        "interval": "day",
        "series": [{"kind": "EventsNode", "event": "signed_up", "math": "dau"}],
    },
}


class _RecordingJudge:
    """Captures what it is handed, and fires so the result shape is observable."""

    seen: list[tuple[SeriesContext, JudgeAttribution]] = []
    judgment: SeriesJudgment | None = None

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def judge_latest(
        self, data: np.ndarray, *, series: SeriesContext, attribution: JudgeAttribution
    ) -> SeriesJudgment | None:
        _RecordingJudge.seen.append((series, attribution))
        return _RecordingJudge.judgment

    def judge_every_point(
        self, data: np.ndarray, *, series: SeriesContext, attribution: JudgeAttribution
    ) -> SeriesJudgment | None:
        raise AssertionError("a live check judges the latest point only")


# The judge only reads identity off these, so a mock avoids a Postgres round trip for a
# test that scores an in-memory series.
FAKE_TEAM = MagicMock(spec=Team)
FAKE_USER = MagicMock(spec=User)


class _FakeInsight:
    id = 42
    name = "Daily signups"
    query = TRENDS_QUERY
    team = FAKE_TEAM


class _FakeAlert:
    id = "b8f3a1e0-0000-0000-0000-000000000001"
    config: dict[str, Any] = {"type": "TrendsAlertConfig", "series_index": 0}
    created_by: Any = FAKE_USER
    next_check_at = datetime(2026, 1, 5, tzinfo=UTC)


def _extraction() -> ExtractionResult:
    points = [SeriesPoint(date=f"2026-01-0{i + 1}", value=float(v)) for i, v in enumerate([100, 98, 101, 99, 12])]
    return ExtractionResult(
        series=[ComparableSeries(label="signed_up", points=points, current_index=len(points) - 1)],
        interval_type=None,
    )


def _judgment(**overrides: Any) -> SeriesJudgment:
    defaults: dict[str, Any] = {
        "fires": True,
        "verdict_is_anomaly": True,
        "confidence": 0.88,
        "kind": "drop",
        "rationale": "Signups fell to 12.",
        "model": "claude-sonnet-5",
        "score": 0.88,
        "triggered_indices": (4,),
        "all_scores": (0.88,),
    }
    return SeriesJudgment(**{**defaults, **overrides})


FIRING_JUDGMENT = _judgment()


def _evaluate(
    detector_config: dict[str, Any], alert: Any = None, judgment: SeriesJudgment | None = FIRING_JUDGMENT
) -> Any:
    _RecordingJudge.seen = []
    _RecordingJudge.judgment = judgment
    with patch("products.alerts.backend.evaluation.detector.LLMSeriesJudge", _RecordingJudge):
        return evaluate_with_detector(
            _extraction(),
            detector_config,
            insight=_FakeInsight(),  # type: ignore[arg-type]
            alert=alert or _FakeAlert(),  # type: ignore[arg-type]
            evaluation_id="workflow-run:activity",
        )


class TestJudgePlumbing:
    def test_judge_receives_the_series_meaning_and_who_the_call_runs_as(self) -> None:
        _evaluate({"type": "llm", "instructions": "Only care about drops"})

        series, attribution = _RecordingJudge.seen[0]
        assert series.dates == ("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05")
        assert series.series_label == "signed_up"
        assert series.insight_name == "Daily signups"
        assert series.instructions == "Only care about drops"
        assert "signed_up" in series.metric_description
        assert attribution.team is FAKE_TEAM
        assert attribution.user is FAKE_USER
        assert attribution.evaluation_id == "workflow-run:activity"

    def test_the_description_covers_only_the_points_the_judge_is_shown(self) -> None:
        _evaluate({"type": "llm", "window": 3})

        series, _ = _RecordingJudge.seen[0]
        assert "2026-01-03 to 2026-01-05" in series.metric_description

    def test_an_ai_alert_with_no_creator_is_refused_before_any_call(self) -> None:
        alert = _FakeAlert()
        alert.created_by = None

        with pytest.raises(LLMDetectorMisconfiguredError, match="person who created it was deleted"):
            _evaluate({"type": "llm"}, alert=alert)

        assert _RecordingJudge.seen == []

    def test_a_statistical_detector_needs_no_one_to_run_as(self) -> None:
        # Only a charged call needs attribution, so an alert whose creator is gone must keep
        # evaluating on a statistical detector instead of failing on a check it never makes.
        alert = _FakeAlert()
        alert.created_by = None

        result = _evaluate({"type": "zscore", "threshold": 0.95}, alert=alert)

        assert result.value == 12.0
        assert _RecordingJudge.seen == []


class TestLLMVerdictReachesTheCheck:
    def test_rationale_is_in_the_breach_message_and_the_check_metadata(self) -> None:
        result = _evaluate({"type": "llm", "threshold": 0.7})

        assert result.breaches is not None
        assert "Signups fell to 12." in result.breaches[0]
        assert "using AI detector" in result.breaches[0]
        # The model's number is its own stated confidence, so the message must not call it a probability.
        assert "model confidence:" in result.breaches[0]
        assert "probability" not in result.breaches[0]
        assert result.triggered_metadata == {
            "detector_type": "llm",
            "series_index": 0,
            "insight_id": 42,
            "rationale": "Signups fell to 12.",
            "kind": "drop",
            "verdict_is_anomaly": True,
            "confidence": 0.88,
        }

    def test_a_series_too_short_to_judge_leaves_the_check_uncomputed(self) -> None:
        # No model call happened, so the check must not read as a healthy value with no score.
        result = _evaluate({"type": "llm"}, judgment=None)

        assert result.value is None
        assert result.breaches == []
        assert result.triggered_metadata is None

    def test_statistical_detector_keeps_its_provenance_but_not_its_fit_state_on_the_check(self) -> None:
        # The statistical detectors' metadata is fit state (means, thresholds); persisting it
        # would put internals in front of a person and into the firing event.
        result = _evaluate({"type": "zscore", "threshold": 0.95})

        assert result.triggered_metadata == {"detector_type": "zscore", "series_index": 0, "insight_id": 42}
        assert "Signups fell to 12." not in (result.breaches or [""])[0]

    def test_judge_is_told_which_sql_column_it_reads_and_which_way_the_rows_run(self) -> None:
        class _SqlInsight(_FakeInsight):
            query = {"kind": "HogQLQuery", "query": "SELECT day, signups, failures FROM t ORDER BY day DESC"}

        class _SqlAlert(_FakeAlert):
            config = {"type": "HogQLAlertConfig", "column": "failures", "evaluation": "first_row"}

        _RecordingJudge.seen = []
        _RecordingJudge.judgment = FIRING_JUDGMENT
        with patch("products.alerts.backend.evaluation.detector.LLMSeriesJudge", _RecordingJudge):
            evaluate_with_detector(
                _extraction(),
                {"type": "llm"},
                insight=_SqlInsight(),  # type: ignore[arg-type]
                alert=_SqlAlert(),  # type: ignore[arg-type]
            )

        series, _ = _RecordingJudge.seen[0]
        assert 'Alerted values: column "failures"' in series.metric_description
        assert "the rows were reversed, so the last value is the latest" in series.metric_description
