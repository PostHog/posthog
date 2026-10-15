from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.schema import NodeKind

from posthog.api.services.query import ExecutionMode
from posthog.hogql_queries.query_failure_handling import build_failure_exception
from posthog.query_cache.failures import QueryFailureRecord

from products.alerts.backend.evaluation.contract import (
    AlertExtractionError,
    ComparableSeries,
    ExtractionResult,
    SeriesPoint,
)
from products.alerts.backend.evaluation.dispatcher import EXTRACTORS, check_alert_per_series, run_extractor

IF_STALE = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE


class _Extractor:
    def __init__(self, outcome: Exception | ExtractionResult) -> None:
        self._outcome = outcome

    def extract(self, alert: Any, insight: Any, query: Any, execution_mode: ExecutionMode) -> ExtractionResult:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _run(outcome: Exception | ExtractionResult) -> ExtractionResult:
    return run_extractor(_Extractor(outcome), MagicMock(), MagicMock(), {}, IF_STALE)


def _breaker_replay() -> Exception:
    return build_failure_exception(
        QueryFailureRecord(
            kind="too_many_bytes",
            detail="Query read too many bytes.",
            consecutive_failures=1,
            last_failed_at=datetime.now(UTC),
            open_until=datetime.now(UTC) + timedelta(hours=1),
        )
    )


@pytest.mark.parametrize(
    "detail,expected_message",
    [
        ("Funnels require at least two steps.", "Funnels require at least two steps."),
        ({"query": ["Action ID 7 does not exist!"]}, "Action ID 7 does not exist!"),
    ],
)
def test_a_rejected_insight_becomes_an_extraction_error(detail, expected_message) -> None:
    with pytest.raises(AlertExtractionError, match=expected_message):
        _run(DRFValidationError(detail))


def test_a_breaker_replay_keeps_the_ordinary_failure_path() -> None:
    # Same exception family, opposite verdict: the insight is sound, so the alert stays enabled.
    replay = _breaker_replay()
    with pytest.raises(type(replay)):
        _run(replay)


def test_a_successful_extraction_passes_through() -> None:
    result = ExtractionResult(series=[])
    assert _run(result) is result


def test_per_series_judges_every_breakdown_value_where_the_alert_stops_at_the_first() -> None:
    series = [
        ComparableSeries(label=label, points=[SeriesPoint(date="2026-09-16", value=value)], current_index=0)
        for label, value in (("Chrome", 150.0), ("Safari", 40.0), ("Firefox", 120.0))
    ]
    alert = MagicMock(
        detector_config=None,
        threshold=MagicMock(configuration={"type": "absolute", "bounds": {"upper": 100}}),
        condition={"type": "absolute_value"},
    )
    alert.insight.query = {"kind": "TrendsQuery"}
    extractor = _Extractor(ExtractionResult(series=series, is_breakdown=True))
    with (
        patch.dict(EXTRACTORS, {NodeKind.TRENDS_QUERY: extractor}),
        patch("products.alerts.backend.evaluation.dispatcher.upgrade_insight", return_value=nullcontext()),
        patch("products.alerts.backend.evaluation.dispatcher.validate_evaluation_delay"),
        patch("products.alerts.backend.evaluation.dispatcher._resolve_execution_mode", return_value=IF_STALE),
    ):
        evaluated = check_alert_per_series(alert)

    assert isinstance(evaluated, tuple)
    assert [(s.label, s.result.value, bool(s.result.breaches)) for s in evaluated] == [
        ("Chrome", 150.0, True),
        ("Safari", 40.0, False),
        ("Firefox", 120.0, True),
    ]
