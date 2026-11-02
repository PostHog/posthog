from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.schema import NodeKind

from posthog.hogql.errors import QueryError

from posthog.api.services.query import ExecutionMode
from posthog.caching.insight_result import InsightResult
from posthog.errors import CHQueryErrorNoCommonType, CHQueryErrorS3FileChangedDuringRead
from posthog.hogql_queries.query_failure_handling import build_failure_exception
from posthog.query_cache.failures import QueryFailureRecord

from products.alerts.backend.evaluation.contract import (
    AlertExtractionError,
    ComparableSeries,
    ExtractionResult,
    SeriesPoint,
)
from products.alerts.backend.evaluation.dispatcher import (
    EXTRACTORS,
    PerSeriesEvaluation,
    check_alert_per_series,
    run_extractor,
)

IF_STALE = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE


class _Extractor:
    def __init__(self, outcome: Exception | ExtractionResult) -> None:
        self._outcome = outcome

    def extract(
        self,
        alert: Any,
        insight: Any,
        query: Any,
        execution_mode: ExecutionMode,
        cache_age_seconds: int | None = None,
    ) -> ExtractionResult:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _run(outcome: Exception | ExtractionResult, query: dict | None = None) -> ExtractionResult:
    return run_extractor(_Extractor(outcome), MagicMock(), MagicMock(), query or {}, IF_STALE)


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


@pytest.mark.parametrize(
    "error,expected_message",
    [
        (
            CHQueryErrorNoCommonType(
                "Code: 386. DB::Exception: There is no supertype for types DateTime64(6, 'UTC'), String. Stack trace: ...",
                code=386,
                code_name="no_common_type",
            ),
            r"^There is no supertype for types DateTime64\(6, 'UTC'\), String\.$",
        ),
        (
            QueryError("Function 'toStartOfHour' expects 1 argument, found 2"),
            r"^Function 'toStartOfHour' expects 1 argument, found 2$",
        ),
    ],
    ids=["clickhouse", "hogql"],
)
def test_a_sql_query_the_engine_rejects_becomes_an_extraction_error(error, expected_message) -> None:
    with pytest.raises(AlertExtractionError, match=expected_message):
        _run(error, {"kind": NodeKind.HOG_QL_QUERY, "query": "select 1"})


@pytest.mark.parametrize(
    "error,query",
    [
        (CHQueryErrorNoCommonType("no supertype", code=386), {"kind": NodeKind.TRENDS_QUERY, "series": []}),
        (CHQueryErrorS3FileChangedDuringRead("file changed", code=36), {"kind": NodeKind.HOG_QL_QUERY}),
        (QueryError("Unknown function"), {"kind": NodeKind.TRENDS_QUERY, "series": []}),
    ],
    ids=["posthog_built_query", "transient_error", "posthog_built_hogql"],
)
def test_a_query_error_outside_the_owners_sql_keeps_the_ordinary_failure_path(error, query) -> None:
    with pytest.raises(type(error)):
        _run(error, query)


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
    query_slot = MagicMock(return_value=nullcontext())
    with (
        patch.dict(EXTRACTORS, {NodeKind.TRENDS_QUERY: extractor}),
        patch("products.alerts.backend.evaluation.dispatcher.upgrade_insight", return_value=nullcontext()),
        patch("products.alerts.backend.evaluation.dispatcher.validate_evaluation_delay"),
        patch("products.alerts.backend.evaluation.dispatcher._resolve_execution_mode", return_value=IF_STALE),
    ):
        evaluated = check_alert_per_series(alert, query_slot=query_slot)

    query_slot.assert_called_once_with()
    assert isinstance(evaluated, PerSeriesEvaluation)
    assert [(s.label, s.result.value, bool(s.result.breaches)) for s in evaluated.series] == [
        ("Chrome", 150.0, True),
        ("Safari", 40.0, False),
        ("Firefox", 120.0, True),
    ]


def _breakdown_row(breakdown_value: list[str], label: str) -> dict[str, Any]:
    return {
        "data": [150.0, 150.0],
        "days": ["2026-09-15", "2026-09-16"],
        "label": label,
        "breakdown_value": breakdown_value,
        "order": 0,
    }


@pytest.mark.parametrize(
    "rows, has_more, expected_identities, truncated",
    [
        (
            [_breakdown_row(["a::b", "c"], "a::b::c"), _breakdown_row(["a", "b::c"], "a::b::c")],
            False,
            ['[0,["a::b","c"]]', '[0,["a","b::c"]]'],
            False,
        ),
        ([_breakdown_row(["a", "c"], "a::c")], True, ['[0,["a","c"]]'], True),
        ([], False, [], False),
    ],
    ids=["labels_that_render_alike", "past_the_breakdown_limit", "no_rows"],
)
def test_per_series_keys_trends_breakdowns_on_their_raw_values(
    rows: list[dict[str, Any]], has_more: bool, expected_identities: list[str], truncated: bool
) -> None:
    alert = MagicMock(
        detector_config=None,
        evaluation_delay_intervals=0,
        config={"type": "TrendsAlertConfig", "series_index": 0},
        threshold=MagicMock(configuration={"type": "absolute", "bounds": {"lower": 200}}),
        condition={"type": "absolute_value"},
        team=MagicMock(base_currency="USD", timezone="UTC"),
    )
    alert.insight.query = {
        "kind": "TrendsQuery",
        "series": [{"kind": "EventsNode", "event": "$pageview"}],
        "interval": "day",
        "breakdownFilter": {"breakdowns": [{"property": "a"}, {"property": "b"}]},
    }
    calculated = InsightResult(
        result=rows, has_more=has_more, columns=[], timezone="UTC", last_refresh=None, cache_key="", is_cached=False
    )
    with (
        patch("products.alerts.backend.evaluation.trends.calculate_for_query_based_insight", return_value=calculated),
        patch("products.alerts.backend.evaluation.dispatcher.upgrade_insight", return_value=nullcontext()),
    ):
        evaluated = check_alert_per_series(alert)

    assert isinstance(evaluated, PerSeriesEvaluation)
    assert [series.identity for series in evaluated.series] == expected_identities
    assert evaluated.truncated is truncated
