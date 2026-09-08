from parameterized import parameterized

from posthog.temporal.ai.anomaly_investigation.metric_definition import UNAVAILABLE, describe_metric_definition
from posthog.temporal.ai.anomaly_investigation.prompts import build_anomaly_context, describe_detector

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
        detector_config={"type": "zscore", "preprocessing": {"diffs_n": 1}},
        triggered_dates=["2026-08-10"],
        triggered_metadata=None,
        calculated_value=474.0,
        interval="hour",
        metric_definition=describe_metric_definition(PAGEVIEW_DAU_ON_ERROR_TRACKING_PAGES),
    )

    assert '"$pageview"' in context
    assert "unique users (DAU)" in context
    assert "change from the previous bucket" in context


# A SQL insight whose alerted column is not built from the first table the statement names.
# The padded comment puts the second source and the final SELECT past the old 800-character
# SQL cut, which is what hid them from the agent.
SQL_OVER_TWO_SOURCES = {
    "kind": "DataVisualizationNode",
    "source": {
        "kind": "HogQLQuery",
        "query": (
            "WITH hourly AS (\n"
            "    SELECT toStartOfHour(bucket) AS slot, sum(spend) AS spend_total\n"
            "    FROM warehouse_hourly_spend\n"
            "    GROUP BY slot\n"
            "),\n"
            "-- " + "padding to push the rest of the statement past a tail-only clip. " * 20 + "\n"
            "per_job AS (\n"
            "    SELECT properties.job_id AS job, sum(properties.cost) AS job_cost\n"
            "    FROM events\n"
            "    WHERE event = '$widget_built'\n"
            "    GROUP BY job\n"
            ")\n"
            "SELECT slot AS hour,\n"
            "       spend_total AS mean_spend,\n"
            "       median(job_cost) AS median_job_cost,\n"
            "       median(job_cost) / spend_total AS cost_share\n"
            "FROM hourly LEFT JOIN per_job ON 1 = 1\n"
            "GROUP BY hour, mean_spend"
        ),
    },
    "chartSettings": {
        "yAxis": [
            {"column": "mean_spend", "settings": {"formatting": {"prefix": "$"}}},
            {
                "column": "median_job_cost",
                "settings": {"display": {"label": "median job cost"}},
            },
            {"column": "cost_share", "settings": {"formatting": {"style": "percent"}}},
        ]
    },
}


@parameterized.expand(
    [
        # The alerted column, and a warning that its neighbours are other metrics.
        ("names_the_alerted_column", '"median_job_cost"'),
        ("warns_other_columns_differ", "different metric"),
        # Both sources have to survive the render; the second one is what the old clip dropped.
        ("keeps_the_first_source", "warehouse_hourly_spend"),
        ("keeps_the_second_source", "$widget_built"),
        ("keeps_the_final_select", "median(job_cost)"),
        # The scored column declares no units, so the agent is told not to invent one.
        ("refuses_invented_units", "currency symbol"),
        ("names_the_author_label", "median job cost"),
    ]
)
def test_sql_metric_names_the_scored_column_and_its_sources(_name: str, expected: str) -> None:
    described = describe_metric_definition(
        SQL_OVER_TWO_SOURCES,
        alert_config={"column": "median_job_cost", "evaluation": "last_row", "label_column": "hour"},
    )

    assert expected in described


@parameterized.expand(
    [
        # A prefix only decorates the number, so the agent must not be warned off using it.
        ("currency_prefix", "mean_spend", 'prefix "$"', "currency symbol"),
        # A percent style rewrites the number, and its author is told never to pair it with a "%"
        # suffix, so the prefix and suffix read comes back empty on exactly these columns.
        ("percent_names_the_style", "cost_share", 'style "percent"', "Units declared for the column: none"),
        ("percent_names_the_scale", "cost_share", "multiplied by 100", "Units declared for the column: none"),
    ]
)
def test_declared_units_reach_the_block_instead_of_the_no_units_warning(
    _name: str, column: str, expected: str, forbidden: str
) -> None:
    described = describe_metric_definition(SQL_OVER_TWO_SOURCES, alert_config={"column": column})

    assert expected in described
    assert forbidden not in described


def test_sql_metric_without_a_configured_column_says_so() -> None:
    described = describe_metric_definition(SQL_OVER_TWO_SOURCES, alert_config={})

    assert "not recorded on the alert" in described


def test_insight_description_reaches_the_definition_block() -> None:
    described = describe_metric_definition(
        SQL_OVER_TWO_SOURCES,
        alert_config={"column": "median_job_cost"},
        insight_description="p50 comes from the widget events, not from the spend view.",
    )

    assert "not from the spend view" in described


# The ensemble the detector selector writes by default. Every setting the agent needs sits on a
# sub-detector, and both members difference the series.
DEFAULT_ENSEMBLE = {
    "type": "ensemble",
    "operator": "and",
    "detectors": [
        {"type": "zscore", "threshold": 0.99, "window": 168, "preprocessing": {"diffs_n": 1, "lags_n": 3}},
        {"type": "mad", "threshold": 0.99, "window": 168, "preprocessing": {"diffs_n": 1}},
    ],
}


@parameterized.expand(
    [
        # Differencing is the setting that made the agent call a working alert mis-tuned.
        ("names_the_setting", {"type": "mad", "preprocessing": {"diffs_n": 1}}, "change from the previous bucket"),
        ("forbids_the_bug_claim", {"type": "mad", "preprocessing": {"diffs_n": 1}}, "candidate bug"),
        ("renders_the_window", {"type": "mad", "window": 168}, "168 buckets"),
        ("renders_the_threshold", {"type": "mad", "threshold": 0.95}, "0.95"),
        # Without preprocessing the agent must not assume the level was transformed.
        ("says_when_untransformed", {"type": "zscore"}, "scores the metric's own level"),
        ("names_smoothing", {"type": "mad", "preprocessing": {"smooth_n": 3}}, "averaged over 3 buckets"),
        ("survives_no_config", None, "Detector: threshold"),
        # An ensemble carries its settings a level down, so a top-level read finds none of them.
        ("reaches_ensemble_preprocessing", DEFAULT_ENSEMBLE, "change from the previous bucket"),
        ("reaches_ensemble_window", DEFAULT_ENSEMBLE, "168 buckets"),
        # Which members had to agree decides whether one member firing was enough to alert.
        ("names_ensemble_operator", DEFAULT_ENSEMBLE, "every sub-detector flags it"),
        # A threshold alert is defined by its bounds, which no other field carries.
        ("renders_the_lower_bound", {"type": "threshold", "lower_bound": 2.5}, "below 2.5"),
        ("renders_the_upper_bound", {"type": "threshold", "upper_bound": 9.0}, "above 9.0"),
    ]
)
def test_detector_block_names_what_is_scored(_name: str, config: dict | None, expected: str) -> None:
    assert expected in describe_detector(config)


def test_ensemble_is_never_reported_as_untransformed() -> None:
    described = describe_detector(DEFAULT_ENSEMBLE)

    assert "scores the metric's own level" not in described
    assert "Sub-detector: zscore" in described
    assert "Sub-detector: mad" in described


def test_null_preprocessing_values_read_as_switched_off() -> None:
    described = describe_detector({"type": "mad", "preprocessing": {"diffs_n": 1, "lags_n": None, "smooth_n": None}})

    assert "scores the change" in described
    assert "lagged copies" not in described
