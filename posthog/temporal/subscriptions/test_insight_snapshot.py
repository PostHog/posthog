import json
import datetime as dt

import pytest

from posthog.caching.fetch_from_cache import InsightResult
from posthog.temporal.subscriptions.insight_snapshot import (
    _has_comparison_enabled,
    _scrub_non_finite_floats,
    _serialize_insight_result,
)


@pytest.mark.parametrize(
    "query_json,expected",
    [
        (None, False),
        ("not a dict", False),
        ({}, False),
        ({"source": {"kind": "TrendsQuery"}}, False),
        ({"source": {"kind": "TrendsQuery", "compareFilter": None}}, False),
        ({"source": {"kind": "TrendsQuery", "compareFilter": {}}}, False),
        ({"source": {"kind": "TrendsQuery", "compareFilter": {"compare": False}}}, False),
        ({"source": {"kind": "TrendsQuery", "compareFilter": {"compare": True}}}, True),
        ({"source": {"kind": "TrendsQuery", "compareFilter": {"compare": True, "compare_to": "-7d"}}}, True),
        # bare query object (no DataVisualizationNode wrapper)
        ({"kind": "TrendsQuery", "compareFilter": {"compare": True}}, True),
        ({"kind": "TrendsQuery", "compareFilter": {"compare": False}}, False),
        # non-dict compareFilter should not crash
        ({"source": {"kind": "TrendsQuery", "compareFilter": "broken"}}, False),
    ],
)
def test_has_comparison_enabled(query_json, expected):
    assert _has_comparison_enabled(query_json) is expected


@pytest.mark.parametrize(
    "value,expected",
    [
        # finite scalars pass through unchanged (int, bool, None, str)
        (1.5, 1.5),
        (1, 1),
        (True, True),
        (None, None),
        ("nan", "nan"),
        # non-finite scalars become None
        (float("nan"), None),
        (float("inf"), None),
        (float("-inf"), None),
        # tuple → list coercion (JSON has no tuples)
        ((float("nan"), 2.0), [None, 2.0]),
        # the real prod shape: funnel row with 0/0 conversion rate
        (
            [["Final: prayer_screen_viewed", 0, 0.0, float("nan")]],
            [["Final: prayer_screen_viewed", 0, 0.0, None]],
        ),
        # nested dict + list mix
        ({"a": float("nan"), "b": [float("inf"), 1]}, {"a": None, "b": [None, 1]}),
    ],
)
def test_scrub_non_finite_floats(value, expected):
    assert _scrub_non_finite_floats(value) == expected


def test_serialize_insight_result_nan_round_trips_through_json():
    result = InsightResult(
        result=[[float("nan"), 1.0, float("inf")]],
        columns=["a", "b", "c"],
        types=["float", "float", "float"],
        last_refresh=dt.datetime(2026, 4, 20, tzinfo=dt.UTC),
        is_cached=False,
        timezone="UTC",
        has_more=False,
        resolved_date_range=None,
        query_status=None,
        cache_key=None,
        cache_target_age=None,
        next_allowed_client_refresh=None,
        hogql=None,
    )

    serialized = _serialize_insight_result(result)

    reparsed = json.loads(json.dumps(serialized))
    assert reparsed["result"] == [[None, 1.0, None]]
