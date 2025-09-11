from typing import Any

from django.test.testcases import TestCase

from parameterized import parameterized
from pydantic import BaseModel

from posthog.schema import (
    BaseMathType,
    BreakdownAttributionType,
    EventPropertyFilter,
    EventsNode,
    FunnelConversionWindowTimeUnit,
    FunnelExclusionEventsNode,
    FunnelsQuery,
    FunnelStepReference,
    FunnelVizType,
    PersonPropertyFilter,
    PropertyOperator,
    RetentionQuery,
    StepOrderValue,
    TrendsQuery,
)

from posthog.schema_helpers import to_dict

base_trends: dict[str, Any] = {"series": []}
base_funnel: dict[str, Any] = {"series": []}


class TestSchemaHelpers(TestCase):
    maxDiff = None

    def test_serializes_to_differing_json_for_default_value(self):
        """
        The property filters have a `type` key with a literal default value.
        This test makes sure that the value actually gets serialized, so that otherwise
        equal property filters can be distinguished.
        """

        q1 = EventPropertyFilter(key="abc", operator=PropertyOperator.GT)
        q2 = PersonPropertyFilter(key="abc", operator=PropertyOperator.GT)

        self.assertNotEqual(to_dict(q1), to_dict(q2))
        self.assertIn("'type': 'event'", str(to_dict(q1)))

    def test_serializes_to_same_json_for_default_value(self):
        """
        The property filters have an optional `operator` key, with
        a default value. This test makes sure that different ways of
        specifying the default value get serialized in the same way.
        """

        q1 = EventPropertyFilter(key="abc")
        q2 = EventPropertyFilter(key="abc", operator=None)
        q3 = EventPropertyFilter(key="abc", operator=PropertyOperator.EXACT)

        self.assertEqual(to_dict(q1), to_dict(q2))
        self.assertEqual(to_dict(q2), to_dict(q3))
        self.assertNotIn("operator", str(to_dict(q1)))

    def test_serializes_empty_and_missing_insight_filter_equally(self):
        q1 = TrendsQuery(**base_trends)
        q2 = TrendsQuery(**{**base_trends, "trendsFilter": {}})

        self.assertEqual(to_dict(q1), {"kind": "TrendsQuery", "series": []})
        self.assertEqual(to_dict(q2), {"kind": "TrendsQuery", "series": []})

    def test_serializes_empty_and_missing_breakdown_filter_equally(self):
        q1 = TrendsQuery(**base_trends)
        q2 = TrendsQuery(**{**base_trends, "breakdownFilter": {}})

        self.assertEqual(to_dict(q1), {"kind": "TrendsQuery", "series": []})
        self.assertEqual(to_dict(q2), {"kind": "TrendsQuery", "series": []})

    def test_serializes_empty_and_missing_date_range_equally(self):
        q1 = TrendsQuery(**base_trends)
        q2 = TrendsQuery(**{**base_trends, "dateRange": {}})

        self.assertEqual(to_dict(q1), {"kind": "TrendsQuery", "series": []})
        self.assertEqual(to_dict(q2), {"kind": "TrendsQuery", "series": []})

    def test_serializes_series_without_frontend_only_props(self):
        query = TrendsQuery(**{**base_trends, "series": [EventsNode(name="$pageview", custom_name="My custom name")]})

        result_dict = to_dict(query)

        self.assertEqual(result_dict, {"kind": "TrendsQuery", "series": [{"name": "$pageview"}]})

    def test_serializes_insight_filter_without_frontend_only_props(self):
        query = TrendsQuery(**{**base_trends, "trendsFilter": {"showLegend": True}})

        result_dict = to_dict(query)

        self.assertEqual(result_dict, {"kind": "TrendsQuery", "series": []})

    def test_serializes_retention_filter_without_frontend_only_props(self):
        query = RetentionQuery(**{"retentionFilter": {"targetEntity": {"uuid": "1"}, "returningEntity": {"uuid": "2"}}})

        result_dict = to_dict(query)

        self.assertEqual(
            result_dict, {"kind": "RetentionQuery", "retentionFilter": {"targetEntity": {}, "returningEntity": {}}}
        )

    def test_serializes_display_with_canonic_alternatives(self):
        # time series (gets removed as ActionsLineGraph is the default)
        query = TrendsQuery(**{**base_trends, "trendsFilter": {"display": "ActionsAreaGraph"}})
        self.assertEqual(to_dict(query), {"kind": "TrendsQuery", "series": []})

        # cumulative time series
        query = TrendsQuery(**{**base_trends, "trendsFilter": {"display": "ActionsLineGraphCumulative"}})
        self.assertEqual(
            to_dict(query),
            {"kind": "TrendsQuery", "series": [], "trendsFilter": {"display": "ActionsLineGraphCumulative"}},
        )

        # total value
        query = TrendsQuery(**{**base_trends, "trendsFilter": {"display": "BoldNumber"}})
        self.assertEqual(
            to_dict(query),
            {"kind": "TrendsQuery", "series": [], "trendsFilter": {"display": "ActionsBarValue"}},
        )

    def _assert_filter(self, key: str, num_keys: int, q1: BaseModel, q2: BaseModel):
        self.assertEqual(to_dict(q1), to_dict(q2))
        if num_keys == 0:
            self.assertEqual(key in to_dict(q1), False)
        else:
            self.assertEqual(num_keys, len(to_dict(q1)[key].keys()))

    @parameterized.expand(
        [
            ({}, {"explicitDate": False}, 0),
            ({"date_to": "2024-02-02"}, {"date_to": "2024-02-02"}, 1),
        ]
    )
    def test_serializes_date_range(self, f1, f2, num_keys):
        q1 = TrendsQuery(**base_funnel, dateRange=f1)
        q2 = TrendsQuery(**base_funnel, dateRange=f2)

        self._assert_filter("dateRange", num_keys, q1, q2)

    @parameterized.expand(
        [
            # general: missing filter
            (None, {}, 0),
            ({}, {"display": "ActionsLineGraph"}, 0),
            ({"display": "BoldNumber"}, {"display": "BoldNumber"}, 1),
        ]
    )
    def test_serializes_trends_filter(self, f1, f2, num_keys):
        q1 = TrendsQuery(**base_funnel, trendsFilter=f1)
        q2 = TrendsQuery(**base_funnel, trendsFilter=f2)

        self._assert_filter("trendsFilter", num_keys, q1, q2)

    @parameterized.expand(
        [
            # general: missing filter
            (None, {}, 0),
            # general: ordering of keys
            (
                {"funnelVizType": FunnelVizType.TIME_TO_CONVERT, "funnelOrderType": StepOrderValue.STRICT},
                {"funnelOrderType": StepOrderValue.STRICT, "funnelVizType": FunnelVizType.TIME_TO_CONVERT},
                2,
            ),
            # binCount
            # ({}, {"binCount": 4}, 0),
            (
                {"binCount": 4, "funnelVizType": FunnelVizType.TIME_TO_CONVERT},
                {"binCount": 4, "funnelVizType": FunnelVizType.TIME_TO_CONVERT},
                2,
            ),
            # breakdownAttributionType
            ({}, {"breakdownAttributionType": BreakdownAttributionType.FIRST_TOUCH}, 0),
            (
                {"breakdownAttributionType": BreakdownAttributionType.LAST_TOUCH},
                {"breakdownAttributionType": BreakdownAttributionType.LAST_TOUCH},
                1,
            ),
            # breakdownAttributionValue
            # ({}, {"breakdownAttributionValue": 2}, 0),
            (
                {"breakdownAttributionType": BreakdownAttributionType.STEP, "breakdownAttributionValue": 2},
                {"breakdownAttributionType": BreakdownAttributionType.STEP, "breakdownAttributionValue": 2},
                2,
            ),
            # exclusions
            ({}, {"exclusions": []}, 0),
            (
                {"exclusions": [FunnelExclusionEventsNode(funnelFromStep=0, funnelToStep=1)]},
                {"exclusions": [FunnelExclusionEventsNode(funnelFromStep=0, funnelToStep=1)]},
                1,
            ),
            # funnelAggregateByHogQL
            # ({}, {"funnelAggregateByHogQL": ""}, 1),
            ({"funnelAggregateByHogQL": "distinct_id"}, {"funnelAggregateByHogQL": "distinct_id"}, 1),
            # funnelFromStep and funnelToStep
            ({"funnelFromStep": 1, "funnelToStep": 2}, {"funnelFromStep": 1, "funnelToStep": 2}, 2),
            # funnelOrderType
            ({}, {"funnelOrderType": StepOrderValue.ORDERED}, 0),
            ({"funnelOrderType": StepOrderValue.STRICT}, {"funnelOrderType": StepOrderValue.STRICT}, 1),
            # funnelStepReference
            ({}, {"funnelStepReference": FunnelStepReference.TOTAL}, 0),
            (
                {"funnelStepReference": FunnelStepReference.PREVIOUS},
                {"funnelStepReference": FunnelStepReference.PREVIOUS},
                1,
            ),
            # funnelVizType
            ({}, {"funnelVizType": FunnelVizType.STEPS}, 0),
            ({"funnelVizType": FunnelVizType.TRENDS}, {"funnelVizType": FunnelVizType.TRENDS}, 1),
            # funnelWindowInterval
            ({}, {"funnelWindowInterval": 14}, 0),
            ({"funnelWindowInterval": 12}, {"funnelWindowInterval": 12}, 1),
            # funnelWindowIntervalUnit
            ({}, {"funnelWindowIntervalUnit": FunnelConversionWindowTimeUnit.DAY}, 0),
            (
                {"funnelWindowIntervalUnit": FunnelConversionWindowTimeUnit.WEEK},
                {"funnelWindowIntervalUnit": FunnelConversionWindowTimeUnit.WEEK},
                1,
            ),
            # hidden_legend_breakdowns
            # ({}, {"hidden_legend_breakdowns": []}, 0),
            # layout
            ({}, {"breakdownAttributionType": BreakdownAttributionType.FIRST_TOUCH}, 0),
            (
                {"breakdownAttributionType": BreakdownAttributionType.LAST_TOUCH},
                {"breakdownAttributionType": BreakdownAttributionType.LAST_TOUCH},
                1,
            ),
        ]
    )
    def test_serializes_funnels_filter(self, f1, f2, num_keys):
        q1 = FunnelsQuery(**base_funnel, funnelsFilter=f1)
        q2 = FunnelsQuery(**base_funnel, funnelsFilter=f2)

        self._assert_filter("funnelsFilter", num_keys, q1, q2)

    def test_series_math_set_to_dau_when_appropriate(self):
        query_with_day_interval = TrendsQuery(
            interval="week", series=[EventsNode(name="$pageview", math=BaseMathType.WEEKLY_ACTIVE)]
        )
        result = to_dict(query_with_day_interval)
        self.assertEqual(result["series"][0]["math"], BaseMathType.DAU)

        query_with_day_interval = TrendsQuery(
            interval="week", series=[EventsNode(name="$pageview", math=BaseMathType.MONTHLY_ACTIVE)]
        )
        result = to_dict(query_with_day_interval)
        self.assertEqual(result["series"][0]["math"], BaseMathType.MONTHLY_ACTIVE)

        query_with_day_interval = TrendsQuery(
            interval="month", series=[EventsNode(name="$pageview", math=BaseMathType.MONTHLY_ACTIVE)]
        )
        result = to_dict(query_with_day_interval)
        self.assertEqual(result["series"][0]["math"], BaseMathType.DAU)

        # Test case where DAU should NOT be set (assuming 'month' interval doesn't trigger it)
        query_with_month_interval = TrendsQuery(
            interval="day", series=[EventsNode(name="$pageview", math=BaseMathType.WEEKLY_ACTIVE)]
        )
        result = to_dict(query_with_month_interval)
        self.assertEqual(result["series"][0]["math"], BaseMathType.WEEKLY_ACTIVE)

        # Test case with existing math that should NOT be overridden
        query_with_existing_math = TrendsQuery(interval="day", series=[EventsNode(name="$pageview")])
        result = to_dict(query_with_existing_math)
        self.assertNotIn("math", result["series"][0])

    def test_serializes_versions_equally(self):
        """
        Nodes with different versions should serialize to the same JSON. We only want the cache key to differ
        if the actual query parameters differ, not the version.
        """
        q1 = TrendsQuery(series=[EventsNode(name="$pageview", version=1)], version=1)
        q2 = TrendsQuery(series=[EventsNode(name="$pageview", version=2)], version=2)

        self.assertEqual(to_dict(q1), to_dict(q2))
