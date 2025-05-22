from ee.clickhouse.views.experiment_convert_legacy_metric import convert_legacy_metric


def test_convert_funnel_query():
    old_query = [
        {
            "kind": "ExperimentFunnelsQuery",
            "name": "My Funnel",
            "funnels_query": {
                "series": [
                    {"kind": "EventsNode", "event": "step1", "name": "Step 1"},
                    {"kind": "EventsNode", "event": "step2", "name": "Step 2"},
                ]
            },
        }
    ]

    result = convert_legacy_metric(old_query)
    assert len(result) == 1
    assert result[0]["kind"] == "ExperimentMetric"
    assert result[0]["metric_type"] == "funnel"
    assert result[0]["name"] == "My Funnel"
    assert len(result[0]["series"]) == 2
    assert "name" not in result[0]["series"][0]
    assert result[0]["series"][0]["event"] == "step1"


def test_convert_trends_query():
    old_query = [
        {
            "kind": "ExperimentTrendsQuery",
            "name": "My Trend",
            "count_query": {
                "series": [
                    {"kind": "EventsNode", "event": "$pageview", "name": "Page Views", "math_property_type": "numeric"}
                ]
            },
        }
    ]

    result = convert_legacy_metric(old_query)
    assert len(result) == 1
    assert result[0]["kind"] == "ExperimentMetric"
    assert result[0]["metric_type"] == "mean"
    assert result[0]["name"] == "My Trend"
    assert "math_property_type" not in result[0]["source"]
    assert "name" not in result[0]["source"]
    assert result[0]["source"]["event"] == "$pageview"


def test_convert_trends_query_with_math():
    old_query = [
        {
            "kind": "ExperimentTrendsQuery",
            "count_query": {
                "series": [{"kind": "EventsNode", "event": "$pageview", "name": "Page Views", "math": "sum"}]
            },
        }
    ]

    result = convert_legacy_metric(old_query)
    assert len(result) == 1
    assert result[0]["source"]["name"] == "Page Views"  # name kept because math exists
