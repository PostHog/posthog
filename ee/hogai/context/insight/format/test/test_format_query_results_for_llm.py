from typing import Any

from unittest import TestCase
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import (
    ChartDisplayType,
    DataTableNode,
    DataVisualizationNode,
    EventsNode,
    HogQLQuery,
    InsightVizNode,
    LifecycleQuery,
    StickinessQuery,
    TrendsFilter,
    TrendsQuery,
)

from .. import format_query_results_for_llm


class TestFormatQueryResultsForLlm(TestCase):
    @parameterized.expand(
        [
            (
                "boxplot_data_uses_boxplot_formatter",
                TrendsQuery(series=[], trendsFilter=TrendsFilter(display=ChartDisplayType.BOX_PLOT)),
                {
                    "results": [
                        {
                            "day": "2025-01-20",
                            "label": "Day 1",
                            "min": 1.0,
                            "p25": 5.0,
                            "median": 10.0,
                            "p75": 20.0,
                            "max": 50.0,
                            "mean": 15.0,
                            "series_label": "$pageview",
                            "series_index": 0,
                        },
                    ],
                },
                "Date|Min|P25|Median|P75|Max|Mean",
            ),
            (
                "trends_without_boxplot_uses_trends_formatter",
                TrendsQuery(series=[]),
                {"results": [{"data": [1], "label": "test", "days": ["2025-01-01"]}]},
                "Date|test",
            ),
            (
                "lifecycle_query",
                LifecycleQuery(series=[EventsNode(event="$pageview")]),
                {
                    "results": [
                        {
                            "data": [10.0],
                            "days": ["2025-01-20"],
                            "labels": ["20-Jan"],
                            "label": "new",
                            "status": "new",
                            "action": {},
                        },
                        {
                            "data": [-5.0],
                            "days": ["2025-01-20"],
                            "labels": ["20-Jan"],
                            "label": "dormant",
                            "status": "dormant",
                            "action": {},
                        },
                    ],
                },
                "Date|New|Returning|Resurrecting|Dormant",
            ),
            (
                "stickiness_query",
                StickinessQuery(series=[EventsNode(event="$pageview")]),
                {
                    "results": [
                        {
                            "count": 100,
                            "data": [50, 30],
                            "days": [1, 2],
                            "labels": ["1 day", "2 days"],
                            "label": "$pageview",
                            "action": {"custom_name": None},
                        },
                    ],
                },
                "Interval|$pageview",
            ),
        ]
    )
    def test_dispatches_correctly(self, _name: str, query, response: dict, expected_substr: str):
        team = MagicMock()
        result = format_query_results_for_llm(query, response, team)
        assert result is not None
        self.assertIn(expected_substr, result)

    def test_boxplot_empty_list_still_uses_boxplot_formatter(self):
        team = MagicMock()
        query = TrendsQuery(series=[], trendsFilter=TrendsFilter(display=ChartDisplayType.BOX_PLOT))
        response: dict[str, Any] = {"results": []}
        result = format_query_results_for_llm(query, response, team)
        self.assertEqual(result, "No data recorded for this time period.")

    @parameterized.expand(
        [
            (
                "insight_viz_node_unwraps_to_trends",
                InsightVizNode(source=TrendsQuery(series=[])),
                {"results": [{"data": [1], "label": "test", "days": ["2025-01-01"]}]},
                "Date|test",
            ),
            (
                "data_visualization_node_unwraps_to_hogql",
                DataVisualizationNode(source=HogQLQuery(query="select 1")),
                {"results": [[1]], "columns": ["one"]},
                "one",
            ),
            (
                "data_table_node_unwraps_to_hogql",
                DataTableNode(source=HogQLQuery(query="select 1")),
                {"results": [[1]], "columns": ["one"]},
                "one",
            ),
        ]
    )
    def test_envelope_nodes_are_unwrapped(self, _name: str, query, response: dict, expected_substr: str):
        team = MagicMock()
        result = format_query_results_for_llm(query, response, team)
        assert result is not None, f"Expected a formatted result, got None for {_name}"
        self.assertIn(expected_substr, result)
