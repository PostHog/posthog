from typing import Any
from parameterized import parameterized

from django.test.testcases import TestCase
from pydantic import BaseModel

from posthog.schema import (
    EventPropertyFilter,
    EventsNode,
    FunnelConversionWindowTimeUnit,
    FunnelExclusionEventsNode,
    FunnelStepReference,
    FunnelsQuery,
    FunnelVizType,
    PersonPropertyFilter,
    PropertyOperator,
    StepOrderValue,
    BreakdownAttributionType,
    TrendsQuery,
    RetentionQuery,
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
        q2 = TrendsQuery(**{**base_trends, "trends_filter": {}})

        self.assertEqual(to_dict(q1), {"kind": "TrendsQuery", "series": []})
        self.assertEqual(to_dict(q2), {"kind": "TrendsQuery", "series": []})

    def test_serializes_empty_and_missing_breakdown_filter_equally(self):
        q1 = TrendsQuery(**base_trends)
        q2 = TrendsQuery(**{**base_trends, "breakdown_filter": {}})

        self.assertEqual(to_dict(q1), {"kind": "TrendsQuery", "series": []})
        self.assertEqual(to_dict(q2), {"kind": "TrendsQuery", "series": []})

    def test_serializes_empty_and_missing_date_range_equally(self):
        q1 = TrendsQuery(**base_trends)
        q2 = TrendsQuery(**{**base_trends, "date_range": {}})

        self.assertEqual(to_dict(q1), {"kind": "TrendsQuery", "series": []})
        self.assertEqual(to_dict(q2), {"kind": "TrendsQuery", "series": []})

    def test_serializes_series_without_frontend_only_props(self):
        query = TrendsQuery(**{**base_trends, "series": [EventsNode(name="$pageview", custom_name="My custom name")]})

        result_dict = to_dict(query)

        self.assertEqual(result_dict, {"kind": "TrendsQuery", "series": [{"name": "$pageview"}]})

    def test_serializes_insight_filter_without_frontend_only_props(self):
        query = TrendsQuery(**{**base_trends, "trends_filter": {"show_legend": True}})

        result_dict = to_dict(query)

        self.assertEqual(result_dict, {"kind": "TrendsQuery", "series": []})

    def test_serializes_retention_filter_without_frontend_only_props(self):
        query = RetentionQuery(
            **{"retention_filter": {"target_entity": {"uuid": "1"}, "returning_entity": {"uuid": "2"}}}
        )

        result_dict = to_dict(query)

        self.assertEqual(
            result_dict, {"kind": "RetentionQuery", "retention_filter": {"target_entity": {}, "returning_entity": {}}}
        )

    def test_serializes_display_with_canonic_alternatives(self):
        # time series (gets removed as ActionsLineGraph is the default)
        query = TrendsQuery(**{**base_trends, "trends_filter": {"display": "ActionsAreaGraph"}})
        self.assertEqual(to_dict(query), {"kind": "TrendsQuery", "series": []})

        # cumulative time series
        query = TrendsQuery(**{**base_trends, "trends_filter": {"display": "ActionsLineGraphCumulative"}})
        self.assertEqual(
            to_dict(query),
            {"kind": "TrendsQuery", "series": [], "trends_filter": {"display": "ActionsLineGraphCumulative"}},
        )

        # total value
        query = TrendsQuery(**{**base_trends, "trends_filter": {"display": "BoldNumber"}})
        self.assertEqual(
            to_dict(query),
            {"kind": "TrendsQuery", "series": [], "trends_filter": {"display": "ActionsBarValue"}},
        )

    def _assert_filter(self, key: str, num_keys: int, q1: BaseModel, q2: BaseModel):
        self.assertEqual(to_dict(q1), to_dict(q2))
        if num_keys == 0:
            self.assertEqual(key in to_dict(q1), False)
        else:
            self.assertEqual(num_keys, len(to_dict(q1)[key].keys()))

    @parameterized.expand(
        [
            ({}, {"date_from": "-7d", "explicit_date": False}, 0),
            ({"date_to": "2024-02-02"}, {"date_to": "2024-02-02"}, 1),
        ]
    )
    def test_serializes_date_range(self, f1, f2, num_keys):
        q1 = TrendsQuery(**base_funnel, date_range=f1)
        q2 = TrendsQuery(**base_funnel, date_range=f2)

        self._assert_filter("date_range", num_keys, q1, q2)

    @parameterized.expand(
        [
            # general: missing filter
            (None, {}, 0),
            ({}, {"display": "ActionsLineGraph"}, 0),
            ({"display": "BoldNumber"}, {"display": "BoldNumber"}, 1),
        ]
    )
    def test_serializes_trends_filter(self, f1, f2, num_keys):
        q1 = TrendsQuery(**base_funnel, trends_filter=f1)
        q2 = TrendsQuery(**base_funnel, trends_filter=f2)

        self._assert_filter("trends_filter", num_keys, q1, q2)

    @parameterized.expand(
        [
            # general: missing filter
            (None, {}, 0),
            # general: ordering of keys
            (
                {"funnel_viz_type": FunnelVizType.TIME_TO_CONVERT, "funnel_order_type": StepOrderValue.STRICT},
                {"funnel_order_type": StepOrderValue.STRICT, "funnel_viz_type": FunnelVizType.TIME_TO_CONVERT},
                2,
            ),
            # bin_count
            # ({}, {"bin_count": 4}, 0),
            (
                {"bin_count": 4, "funnel_viz_type": FunnelVizType.TIME_TO_CONVERT},
                {"bin_count": 4, "funnel_viz_type": FunnelVizType.TIME_TO_CONVERT},
                2,
            ),
            # breakdown_attribution_type
            ({}, {"breakdown_attribution_type": BreakdownAttributionType.FIRST_TOUCH}, 0),
            (
                {"breakdown_attribution_type": BreakdownAttributionType.LAST_TOUCH},
                {"breakdown_attribution_type": BreakdownAttributionType.LAST_TOUCH},
                1,
            ),
            # breakdown_attribution_value
            # ({}, {"breakdown_attribution_value": 2}, 0),
            (
                {"breakdown_attribution_type": BreakdownAttributionType.STEP, "breakdown_attribution_value": 2},
                {"breakdown_attribution_type": BreakdownAttributionType.STEP, "breakdown_attribution_value": 2},
                2,
            ),
            # exclusions
            ({}, {"exclusions": []}, 0),
            (
                {"exclusions": [FunnelExclusionEventsNode(funnel_from_step=0, funnel_to_step=1)]},
                {"exclusions": [FunnelExclusionEventsNode(funnel_from_step=0, funnel_to_step=1)]},
                1,
            ),
            # funnel_aggregate_by_hog_q_l
            # ({}, {"funnel_aggregate_by_hog_q_l": ""}, 1),
            ({"funnel_aggregate_by_hog_q_l": "distinct_id"}, {"funnel_aggregate_by_hog_q_l": "distinct_id"}, 1),
            # funnel_from_step and funnel_to_step
            ({"funnel_from_step": 1, "funnel_to_step": 2}, {"funnel_from_step": 1, "funnel_to_step": 2}, 2),
            # funnel_order_type
            ({}, {"funnel_order_type": StepOrderValue.ORDERED}, 0),
            ({"funnel_order_type": StepOrderValue.STRICT}, {"funnel_order_type": StepOrderValue.STRICT}, 1),
            # funnel_step_reference
            ({}, {"funnel_step_reference": FunnelStepReference.TOTAL}, 0),
            (
                {"funnel_step_reference": FunnelStepReference.PREVIOUS},
                {"funnel_step_reference": FunnelStepReference.PREVIOUS},
                1,
            ),
            # funnel_viz_type
            ({}, {"funnel_viz_type": FunnelVizType.STEPS}, 0),
            ({"funnel_viz_type": FunnelVizType.TRENDS}, {"funnel_viz_type": FunnelVizType.TRENDS}, 1),
            # funnel_window_interval
            ({}, {"funnel_window_interval": 14}, 0),
            ({"funnel_window_interval": 12}, {"funnel_window_interval": 12}, 1),
            # funnel_window_interval_unit
            ({}, {"funnel_window_interval_unit": FunnelConversionWindowTimeUnit.DAY}, 0),
            (
                {"funnel_window_interval_unit": FunnelConversionWindowTimeUnit.WEEK},
                {"funnel_window_interval_unit": FunnelConversionWindowTimeUnit.WEEK},
                1,
            ),
            # hidden_legend_breakdowns
            # ({}, {"hidden_legend_breakdowns": []}, 0),
            # layout
            ({}, {"breakdown_attribution_type": BreakdownAttributionType.FIRST_TOUCH}, 0),
            (
                {"breakdown_attribution_type": BreakdownAttributionType.LAST_TOUCH},
                {"breakdown_attribution_type": BreakdownAttributionType.LAST_TOUCH},
                1,
            ),
        ]
    )
    def test_serializes_funnels_filter(self, f1, f2, num_keys):
        q1 = FunnelsQuery(**base_funnel, funnels_filter=f1)
        q2 = FunnelsQuery(**base_funnel, funnels_filter=f2)

        self._assert_filter("funnels_filter", num_keys, q1, q2)
