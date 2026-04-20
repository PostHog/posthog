import pytest

from posthog.temporal.subscriptions.insight_snapshot import _has_comparison_enabled


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
