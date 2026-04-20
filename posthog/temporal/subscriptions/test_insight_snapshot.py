import json
import datetime as dt
from decimal import Decimal

import pytest

from posthog.caching.fetch_from_cache import InsightResult
from posthog.temporal.subscriptions.insight_snapshot import _has_comparison_enabled, _serialize_insight_result


def _build_insight_result(**overrides) -> InsightResult:
    base: dict = {
        "result": [],
        "columns": [],
        "types": [],
        "last_refresh": dt.datetime(2026, 4, 20, tzinfo=dt.UTC),
        "is_cached": False,
        "timezone": "UTC",
        "has_more": False,
        "resolved_date_range": None,
        "query_status": None,
        "cache_key": None,
        "cache_target_age": None,
        "next_allowed_client_refresh": None,
        "hogql": None,
    }
    base.update(overrides)
    return InsightResult(**base)


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


def test_serialize_insight_result_non_finite_floats_become_null():
    result = _build_insight_result(
        result=[
            [float("nan"), 1.0, float("inf")],
            ["Final: $pageview", 0, 0.0, float("nan")],
        ],
        columns=["a", "b", "c", "d"],
        types=["float", "float", "float", "float"],
    )

    serialized = _serialize_insight_result(result)

    reparsed = json.loads(json.dumps(serialized))
    assert reparsed["result"] == [
        [None, 1.0, None],
        ["Final: $pageview", 0, 0.0, None],
    ]


def test_serialize_insight_result_handles_decimal_and_date():
    # Regression witness: orjson raises on Decimal without a default= hook, and stdlib json
    # raises on bare date. Both used to live on the ClickHouse result path for revenue /
    # analytics queries.
    result = _build_insight_result(
        result=[[Decimal("1.5"), dt.date(2026, 4, 20)]],
        columns=["revenue", "day"],
        types=["Decimal(10,2)", "Date"],
    )

    serialized = _serialize_insight_result(result)

    reparsed = json.loads(json.dumps(serialized))
    assert reparsed["result"] == [["1.5", "2026-04-20"]]
