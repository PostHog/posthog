from parameterized import parameterized

from posthog.temporal.ai.anomaly_investigation.metric_definition import UNAVAILABLE, describe_metric_definition
from posthog.temporal.ai.anomaly_investigation.prompts import build_anomaly_context

# A $pageview DAU series filtered to the app's error tracking pages — an insight whose
# name ("Error tracking active users") reads as an error count but which measures page visits.
PAGEVIEW_DAU_ON_ERROR_TRACKING_PAGES = {
    "kind": "InsightVizNode",
    "source": {
        "kind": "TrendsQuery",
        "interval": "hour",
        "series": [
            {
                "kind": "EventsNode",
                "event": "$pageview",
                "math": "dau",
                "properties": [
                    {
                        "key": "$pathname",
                        "type": "event",
                        "value": "^/project/\\d+/error_tracking(/|$)",
                        "operator": "regex",
                    }
                ],
            }
        ],
    },
}


@parameterized.expand(
    [
        ("event", '"$pageview"'),
        ("aggregation", "unique users (DAU)"),
        ("filter_operator", "matches regex"),
        ("filter_key", "$pathname"),
        ("filter_value", "error_tracking"),
        ("interval", "hour"),
    ]
)
def test_describes_what_the_alerted_series_counts(_name: str, expected: str) -> None:
    described = describe_metric_definition(PAGEVIEW_DAU_ON_ERROR_TRACKING_PAGES)

    assert expected in described


def test_marks_the_alerted_series_by_index() -> None:
    query = {
        "kind": "TrendsQuery",
        "series": [
            {"kind": "EventsNode", "event": "$pageview", "math": "dau"},
            {"kind": "EventsNode", "event": "$exception", "math": "total"},
        ],
    }

    described = describe_metric_definition(query, series_index=1)

    assert 'Alerted series (index 1): total event count of event "$exception"' in described
    assert 'Other series in this insight (index 0): unique users (DAU) of event "$pageview"' in described


def test_flattens_nested_property_groups() -> None:
    query = {
        "kind": "TrendsQuery",
        "series": [{"kind": "EventsNode", "event": "$pageview", "math": "dau"}],
        "properties": {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [{"key": "$host", "type": "event", "value": "eu.posthog.com", "operator": "exact"}],
                }
            ],
        },
    }

    described = describe_metric_definition(query)

    assert "event property $host is eu.posthog.com" in described


@parameterized.expand(
    [
        ("none", None),
        ("empty_dict", {}),
        ("wrong_type", "not a query"),
    ]
)
def test_unreadable_query_says_the_definition_is_unavailable(_name: str, query: object) -> None:
    assert describe_metric_definition(query) == UNAVAILABLE


@parameterized.expand(
    [
        ("series_not_a_list", {"kind": "TrendsQuery", "series": "broken"}),
        ("series_entries_not_dicts", {"kind": "TrendsQuery", "series": [None, 7]}),
        ("filters_not_a_list", {"kind": "TrendsQuery", "series": [{"event": "$pageview", "properties": 3}]}),
    ]
)
def test_malformed_query_degrades_instead_of_raising(_name: str, query: object) -> None:
    assert describe_metric_definition(query)


def test_anomaly_context_carries_the_metric_definition() -> None:
    context = build_anomaly_context(
        alert_name="Error tracking users spike",
        metric_description="Headline: Error tracking active users",
        detector_type="zscore",
        triggered_dates=["2026-08-10"],
        triggered_metadata=None,
        calculated_value=474.0,
        interval="hour",
        metric_definition=describe_metric_definition(PAGEVIEW_DAU_ON_ERROR_TRACKING_PAGES),
    )

    assert '"$pageview"' in context
    assert "unique users (DAU)" in context
