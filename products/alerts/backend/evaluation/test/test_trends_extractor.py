from typing import Any

import pytest

from posthog.schema import TrendsAlertConfig

from posthog.caching.fetch_from_cache import InsightResult

from products.alerts.backend.evaluation.trends import TrendsExtractor


def _insight_result(result: Any) -> InsightResult:
    return InsightResult(result=result, last_refresh=None, cache_key=None, is_cached=False, timezone=None)


@pytest.mark.parametrize(
    "result,is_non_time_series,expected",
    [
        # Time-series result: one point per data value, dated from "dates".
        ({"data": [1.0, 2.0, 3.0], "dates": ["d1", "d2", "d3"]}, False, [("d1", 1.0), ("d2", 2.0), ("d3", 3.0)]),
        # Time-series result without "dates" falls back to "days".
        ({"data": [4.0], "days": ["d1"]}, False, [("d1", 4.0)]),
        # Configured non-time-series result: single aggregated point.
        ({"aggregated_value": 7.0}, True, [(None, 7.0)]),
        # Divergent shape — display type implies a time series but the result carries only an
        # aggregated value. Must degrade to a single point instead of raising KeyError.
        ({"aggregated_value": 9.0}, False, [(None, 9.0)]),
        # Divergent and missing even the aggregated value: a single missing point, still no raise.
        ({"label": "x"}, False, [(None, None)]),
    ],
)
def test_result_to_points(result, is_non_time_series, expected):
    points = TrendsExtractor._result_to_points(result, is_non_time_series)
    assert [(p.date, p.value) for p in points] == expected


def test_to_series_handles_result_missing_data_key():
    """A non-breakdown trend result that diverges from its display type (only aggregated_value,
    no "data") must not raise when extracted as a time series."""
    config = TrendsAlertConfig(type="TrendsAlertConfig", series_index=0)
    calculation_result = _insight_result([{"label": "signed_up", "aggregated_value": 42.0}])

    series = TrendsExtractor()._to_series(
        config,
        calculation_result,
        has_breakdown=False,
        is_non_time_series=False,
        anchor_is_current=True,
    )

    assert len(series) == 1
    assert series[0].label == "signed_up"
    assert [(p.date, p.value) for p in series[0].points] == [(None, 42.0)]
    assert series[0].current_index == 0
