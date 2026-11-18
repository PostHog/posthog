from datetime import UTC, datetime
from typing import Any

import time_machine
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import (
    AssistantDateRange,
    AssistantFunnelsEventsNode,
    AssistantFunnelsFilter,
    AssistantFunnelsQuery,
    EventsNode,
    FunnelAggregateByHogQL,
    FunnelsDataWarehouseNode,
    FunnelsFilter,
    FunnelsQuery,
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

    @parameterized.expand(
        [
            (FunnelVizType.STEPS,),
            (FunnelVizType.TIME_TO_CONVERT,),
            (FunnelVizType.TRENDS,),
        ]
    )
    def test_funnels_none_results(self, viz_type: FunnelVizType):
        query = AssistantFunnelsQuery(series=[], funnelsFilter=AssistantFunnelsFilter(funnelVizType=viz_type))
        self.assertEqual(
            FunnelResultsFormatter(query, None, self.team, datetime.now()).format(),
            "No data recorded for this time period.",
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

        with time_machine.travel("2025-02-07T15:00:00", tick=False):
            self.assertEqual(
                FunnelResultsFormatter(
                    AssistantFunnelsQuery(series=[]),
                    results,
                    self.team,
                    datetime.now(),
                ).format(),
                'Date range: 2025-01-31 00:00:00 to 2025-02-07 23:59:59 (UTC)\n\n---au\nMetric|$pageview|signup\nTotal person count|5|2\nConversion rate|100%|40%\nDropoff rate|0%|60%\nAverage conversion time|-|10s\nMedian conversion time|-|11s\n\n---us\nMetric|$pageview|signup\nTotal person count|5|2\nConversion rate|100%|40%\nDropoff rate|0%|60%\nAverage conversion time|-|10s\nMedian conversion time|-|11s\n\nConversion and drop-off rates are calculated in overall. For example, "Conversion rate: 9%" means that 9% of users from the first step completed the funnel.',
            )

    @parameterized.expand(
        [
            ("person_default", None, None, "Total person count", "users"),
            ("person_id_expression", "person_id", None, "Total person count", "users"),
            (
                "session_expression",
                "properties.$session_id",
                None,
                "Total session count (aggregated by properties.$session_id)",
                "sessions",
            ),
            ("group", None, 1, "Total group count (group type index 1)", "groups"),
            (
                "group_wins_over_expression",
                "properties.$session_id",
                0,
                "Total group count (group type index 0)",
                "groups",
            ),
            (
                "custom_expression",
                "properties.account_id",
                None,
                "Total unique value count (aggregated by properties.account_id)",
                "unique values of properties.account_id",
            ),
            (
                "custom_expression_not_a_property_path",
                "concat(a,\n'x')||b",
                None,
                "Total unique value count (aggregated by a custom HogQL expression)",
                "unique values of the custom HogQL expression",
            ),
        ]
    )
    def test_funnel_steps_count_label_follows_aggregation(
        self, _name: str, hogql: str | None, group_type_index: int | None, count_label: str, unit: str
    ):
        query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="signup")],
            aggregation_group_type_index=group_type_index,
            funnelsFilter=FunnelsFilter(funnelAggregateByHogQL=hogql),
        )
        results = [
            {"name": "$pageview", "count": 5, "average_conversion_time": None, "median_conversion_time": None},
            {"name": "signup", "count": 2, "average_conversion_time": 10, "median_conversion_time": 11},
        ]
        output = FunnelResultsFormatter(query, results, self.team, datetime.now()).format()
        self.assertIn(f"\n{count_label}|5|2\n", output)
        self.assertIn(f"means that 9% of {unit} from the first step completed the funnel.", output)

    def test_funnel_steps_count_label_for_custom_data_warehouse_target(self):
        warehouse_step = {
            "table_name": "opportunities",
            "id_field": "id",
            "timestamp_field": "created_at",
            "aggregation_target_field": "account_id",
        }
        query = FunnelsQuery(
            series=[
                FunnelsDataWarehouseNode(id="opportunities", name="created", **warehouse_step),
                FunnelsDataWarehouseNode(id="opportunities", name="won", **warehouse_step),
            ],
            funnelsFilter=FunnelsFilter(customAggregationTarget=True),
        )
        results = [
            {"name": "created", "count": 5, "average_conversion_time": None, "median_conversion_time": None},
            {"name": "won", "count": 2, "average_conversion_time": 10, "median_conversion_time": 11},
        ]
        output = FunnelResultsFormatter(query, results, self.team, datetime.now()).format()
        self.assertIn("\nTotal entity count|5|2\n", output)
        self.assertIn("means that 9% of entities from the first step completed the funnel.", output)

    def test_assistant_funnel_session_aggregation(self):
        query = AssistantFunnelsQuery(
            series=[AssistantFunnelsEventsNode(event="$pageview"), AssistantFunnelsEventsNode(event="signup")],
            funnelsFilter=AssistantFunnelsFilter(
                funnelAggregateByHogQL=FunnelAggregateByHogQL.PROPERTIES__SESSION_ID,
                funnelVizType=FunnelVizType.TIME_TO_CONVERT,
            ),
        )
        results = {"average_conversion_time": 600, "bins": [[600, 1]]}
        output = FunnelResultsFormatter(query, results, self.team, datetime.now()).format()
        self.assertIn("Average time to convert|Session distribution\n10m|100%", output)
        self.assertIn("The session distribution is the percentage of sessions who completed the funnel", output)

    def test_funnels_time_to_convert(self):
        query = AssistantFunnelsQuery(
            series=[
                AssistantFunnelsEventsNode(event="$pageview", custom_name="custom"),
                AssistantFunnelsEventsNode(event="$ai_trace"),
            ],
            dateRange=AssistantDateRange(date_from="2025-01-20", date_to="2025-01-22"),
            funnelsFilter=AssistantFunnelsFilter(funnelVizType=FunnelVizType.TIME_TO_CONVERT),
        )
        results = {"average_conversion_time": 600, "bins": [[600, 15], [601, 0], [602, 5]]}
        self.assertEqual(
            FunnelResultsFormatter(query, results, self.team, datetime.now()).format(),
            "Date range: 2025-01-20 00:00:00 to 2025-01-22 23:59:59 (UTC)\n\nEvents: $pageview (custom) -> $ai_trace\nAverage time to convert|User distribution\n10m|75%\n10m 1s|0%\n10m 2s|25%\n\nThe user distribution is the percentage of users who completed the funnel in the given period.",
        )

    def test_funnels_time_to_convert_with_only_empty_bins(self):
        query = AssistantFunnelsQuery(
            series=[AssistantFunnelsEventsNode(event="$pageview"), AssistantFunnelsEventsNode(event="signup")],
            funnelsFilter=AssistantFunnelsFilter(funnelVizType=FunnelVizType.TIME_TO_CONVERT),
        )
        results = {"average_conversion_time": None, "bins": [[600, 0], [601, 0]]}
        output = FunnelResultsFormatter(query, results, self.team, datetime.now()).format()
        self.assertIn("Average time to convert|User distribution\n10m|0%\n10m 1s|0%", output)

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

    def test_funnel_trends_marks_partial_bucket(self):
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
            dateRange=AssistantDateRange(date_from="2025-01-08"),
            funnelsFilter=AssistantFunnelsFilter(funnelVizType=FunnelVizType.TRENDS),
        )
        # now is midday on the 10th, so the 10th's bucket is still collecting.
        self.assertEqual(
            FunnelResultsFormatter(query, results, self.team, datetime(2025, 1, 10, 12, 0, 0, tzinfo=UTC)).format(),
            "Date|$pageview (custom) -> $ai_trace conversion|$pageview (custom) -> $ai_trace drop-off\n"
            "2025-01-08|10%|90%\n2025-01-09|15.5%|84.5%\n2025-01-10 (partial)|0%|100%\n\n"
            'Note: rows marked "(partial)" cover an interval that is still in progress as of the query time, '
            "so their values are incomplete. Timezone: UTC.",
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
