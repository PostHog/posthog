from datetime import datetime
from typing import Any

from freezegun import freeze_time
from posthog.test.base import BaseTest

from posthog.schema import (
    AssistantDateRange,
    AssistantFunnelsEventsNode,
    AssistantFunnelsFilter,
    AssistantFunnelsQuery,
    FunnelStepReference,
    FunnelVizType,
)

from .. import FunnelResultsFormatter


class TestFunnelResultsFormatter(BaseTest):
    def test_funnels_single_series(self):
        results: list[dict[str, Any]] = [
            {
                "action_id": "$pageview",
                "name": "$pageview",
                "custom_name": "custom",
                "order": 0,
                "people": [],
                "count": 5,
                "type": "events",
                "average_conversion_time": None,
                "median_conversion_time": None,
            },
            {
                "action_id": "$pageview",
                "name": "$pageview",
                "custom_name": None,
                "order": 1,
                "people": [],
                "count": 2,
                "type": "events",
                "average_conversion_time": 10,
                "median_conversion_time": 11,
            },
            {
                "action_id": "$pageview",
                "name": "$pageview",
                "custom_name": None,
                "order": 2,
                "people": [],
                "count": 1,
                "type": "events",
                "average_conversion_time": 20,
                "median_conversion_time": 22,
            },
        ]
        self.assertIn(
            "Metric|$pageview custom|$pageview|$pageview\nTotal person count|5|2|1\nConversion rate|100%|40%|20%\nDropoff rate|0%|60%|80%\nAverage conversion time|-|10s|20s\nMedian conversion time|-|11s|22s",
            FunnelResultsFormatter(AssistantFunnelsQuery(series=[]), results, self.team, datetime.now()).format(),
        )
        self.assertIn(
            "Metric|$pageview custom|$pageview|$pageview\nTotal person count|5|2|1\nConversion rate|100%|40%|50%\nDropoff rate|0%|60%|50%\nAverage conversion time|-|10s|20s\nMedian conversion time|-|11s|22s",
            FunnelResultsFormatter(
                AssistantFunnelsQuery(
                    series=[], funnelsFilter=AssistantFunnelsFilter(funnelStepReference=FunnelStepReference.PREVIOUS)
                ),
                results,
                self.team,
                datetime.now(),
            ).format(),
        )

    def test_funnels_with_zero_count(self):
        results: list[dict[str, Any]] = [
            {
                "action_id": "$pageview",
                "name": "$pageview",
                "custom_name": "custom",
                "order": 0,
                "people": [],
                "count": 0,
                "type": "events",
                "average_conversion_time": None,
                "median_conversion_time": None,
            },
            {
                "action_id": "$pageview",
                "name": "$pageview",
                "custom_name": None,
                "order": 1,
                "people": [],
                "count": 0,
                "type": "events",
                "average_conversion_time": None,
                "median_conversion_time": None,
            },
        ]
        self.assertIn(
            "Metric|$pageview custom|$pageview\nTotal person count|0|0\nConversion rate|100%|0%\nDropoff rate|0%|100%\nAverage conversion time|-|-\nMedian conversion time|-|-",
            FunnelResultsFormatter(AssistantFunnelsQuery(series=[]), results, self.team, datetime.now()).format(),
        )
        self.assertIn(
            "Metric|$pageview custom|$pageview\nTotal person count|0|0\nConversion rate|100%|0%\nDropoff rate|0%|100%\nAverage conversion time|-|-\nMedian conversion time|-|-",
            FunnelResultsFormatter(
                AssistantFunnelsQuery(
                    series=[], funnelsFilter=AssistantFunnelsFilter(funnelStepReference=FunnelStepReference.PREVIOUS)
                ),
                results,
                self.team,
                datetime.now(),
            ).format(),
        )

    def test_funnels_breakdown(self):
        results = [
            {
                "action_id": "$pageview",
                "name": "$pageview",
                "order": 0,
                "people": [],
                "count": 5,
                "type": "events",
                "average_conversion_time": None,
                "median_conversion_time": None,
                "breakdown_value": ["au"],
            },
            {
                "action_id": "signup",
                "name": "signup",
                "order": 1,
                "people": [],
                "count": 2,
                "type": "events",
                "average_conversion_time": 10,
                "median_conversion_time": 11,
                "breakdown_value": ["au"],
            },
        ]
        self.assertIn(
            "---au\nMetric|$pageview|signup\nTotal person count|5|2\nConversion rate|100%|40%\nDropoff rate|0%|60%\nAverage conversion time|-|10s\nMedian conversion time|-|11s",
            FunnelResultsFormatter(AssistantFunnelsQuery(series=[]), results, self.team, datetime.now()).format(),
        )

    def test_funnel_format_multiple_series(self):
        results = [
            [
                {
                    "action_id": "$pageview",
                    "name": "$pageview",
                    "order": 0,
                    "people": [],
                    "count": 5,
                    "type": "events",
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                    "breakdown_value": ["au"],
                },
                {
                    "action_id": "signup",
                    "name": "signup",
                    "order": 1,
                    "people": [],
                    "count": 2,
                    "type": "events",
                    "average_conversion_time": 10,
                    "median_conversion_time": 11,
                    "breakdown_value": ["au"],
                },
            ],
            [
                {
                    "action_id": "$pageview",
                    "name": "$pageview",
                    "order": 0,
                    "people": [],
                    "count": 5,
                    "type": "events",
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                    "breakdown_value": ["us"],
                },
                {
                    "action_id": "signup",
                    "name": "signup",
                    "order": 1,
                    "people": [],
                    "count": 2,
                    "type": "events",
                    "average_conversion_time": 10,
                    "median_conversion_time": 11,
                    "breakdown_value": ["us"],
                },
            ],
        ]

        with freeze_time("2025-02-07T15:00:00"):
            self.assertEqual(
                FunnelResultsFormatter(
                    AssistantFunnelsQuery(series=[]),
                    results,
                    self.team,
                    datetime.now(),
                ).format(),
                'Date range: 2025-01-31 00:00:00 to 2025-02-07 23:59:59\n\n---au\nMetric|$pageview|signup\nTotal person count|5|2\nConversion rate|100%|40%\nDropoff rate|0%|60%\nAverage conversion time|-|10s\nMedian conversion time|-|11s\n\n---us\nMetric|$pageview|signup\nTotal person count|5|2\nConversion rate|100%|40%\nDropoff rate|0%|60%\nAverage conversion time|-|10s\nMedian conversion time|-|11s\n\nConversion and drop-off rates are calculated in overall. For example, "Conversion rate: 9%" means that 9% of users from the first step completed the funnel.',
            )

    def test_funnels_time_to_convert(self):
        query = AssistantFunnelsQuery(
            series=[
                AssistantFunnelsEventsNode(event="$pageview", custom_name="custom"),
                AssistantFunnelsEventsNode(event="$ai_trace"),
            ],
            dateRange=AssistantDateRange(date_from="2025-01-20", date_to="2025-01-22"),
            funnelsFilter=AssistantFunnelsFilter(funnelVizType=FunnelVizType.TIME_TO_CONVERT),
        )
        results = {"average_conversion_time": 600, "bins": [[600, 1], [601, 0]]}
        self.assertEqual(
            FunnelResultsFormatter(query, results, self.team, datetime.now()).format(),
            "Date range: 2025-01-20 00:00:00 to 2025-01-22 23:59:59\n\nEvents: $pageview (custom) -> $ai_trace\nAverage time to convert|User distribution\n10m|100%\n10m 1s|0%\n\nThe user distribution is the percentage of users who completed the funnel in the given period.",
        )

    def test_funnel_trends(self):
        results = [
            {
                "count": 31,
                "data": [10, 15.5, 0],
                "days": ["2025-01-08", "2025-01-09", "2025-01-10"],
                "labels": ["8-Jan-2025", "9-Jan-2025", "10-Jan-2025"],
            }
        ]
        query = AssistantFunnelsQuery(
            series=[
                AssistantFunnelsEventsNode(event="$pageview", custom_name="custom"),
                AssistantFunnelsEventsNode(event="$ai_trace"),
            ],
            dateRange=AssistantDateRange(date_from="2025-01-08", date_to="2025-01-10"),
            funnelsFilter=AssistantFunnelsFilter(funnelVizType=FunnelVizType.TRENDS),
        )
        self.assertEqual(
            FunnelResultsFormatter(query, results, self.team, datetime.now()).format(),
            "Date|$pageview (custom) -> $ai_trace conversion|$pageview (custom) -> $ai_trace drop-off\n2025-01-08|10%|90%\n2025-01-09|15.5%|84.5%\n2025-01-10|0%|100%",
        )

    def test_funnel_trends_with_breakdown(self):
        results = [
            {
                "count": 31,
                "data": [10, 15.5, 0],
                "days": ["2025-01-08", "2025-01-09", "2025-01-10"],
                "labels": ["8-Jan-2025", "9-Jan-2025", "10-Jan-2025"],
                "breakdown_value": ["au"],
            },
            {
                "count": 31,
                "data": [5, 25, 50],
                "days": ["2025-01-08", "2025-01-09", "2025-01-10"],
                "labels": ["8-Jan-2025", "9-Jan-2025", "10-Jan-2025"],
                "breakdown_value": ["us"],
            },
        ]
        query = AssistantFunnelsQuery(
            series=[
                AssistantFunnelsEventsNode(event="$pageview", custom_name="custom"),
                AssistantFunnelsEventsNode(event="$ai_trace"),
            ],
            dateRange=AssistantDateRange(date_from="2025-01-08", date_to="2025-01-10"),
            funnelsFilter=AssistantFunnelsFilter(funnelVizType=FunnelVizType.TRENDS),
        )

        self.assertEqual(
            FunnelResultsFormatter(query, results, self.team, datetime.now()).format(),
            "Date|$pageview (custom) -> $ai_trace au breakdown conversion|$pageview (custom) -> $ai_trace au breakdown drop-off|$pageview (custom) -> $ai_trace us breakdown conversion|$pageview (custom) -> $ai_trace us breakdown drop-off\n2025-01-08|10%|90%|5%|95%\n2025-01-09|15.5%|84.5%|25%|75%\n2025-01-10|0%|100%|50%|50%",
        )
