import json
from typing import Any
from parameterized import parameterized

from django.test.testcases import TestCase
from pydantic import BaseModel

from posthog.schema import (
    EventPropertyFilter,
    FunnelConversionWindowTimeUnit,
    FunnelExclusionEventsNode,
    FunnelStepReference,
    FunnelsQuery,
    FunnelVizType,
    FunnelLayout,
    PersonPropertyFilter,
    PropertyOperator,
    StepOrderValue,
    BreakdownAttributionType,
    TrendsQuery,
)
from posthog.schema_helpers import to_json


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

        q1 = EventPropertyFilter(key="abc", operator=PropertyOperator.gt)
        q2 = PersonPropertyFilter(key="abc", operator=PropertyOperator.gt)

        self.assertNotEqual(to_json(q1), to_json(q2))
        self.assertIn('"type":"event"', str(to_json(q1)))

    def test_serializes_to_same_json_for_default_value(self):
        """
        The property filters have an optional `operator` key, with
        a default value. This test makes sure that different ways of
        specifying the default value get serialized in the same way.
        """

        q1 = EventPropertyFilter(key="abc")
        q2 = EventPropertyFilter(key="abc", operator=None)
        q3 = EventPropertyFilter(key="abc", operator=PropertyOperator.exact)

        self.assertEqual(to_json(q1), to_json(q2))
        self.assertEqual(to_json(q2), to_json(q3))
        self.assertNotIn("operator", str(to_json(q1)))

    def _assert_filter(self, key: str, num_keys: int, q1: BaseModel, q2: BaseModel):
        self.assertEqual(to_json(q1), to_json(q2))
        if num_keys == 0:
            self.assertEqual(key in json.loads(to_json(q1)), False)
        else:
            self.assertEqual(num_keys, len(json.loads(to_json(q1))[key].keys()))

    @parameterized.expand(
        [
            ({}, {"date_from": "-7d", "explicitDate": False}, 0),
            ({"date_to": "2024-02-02"}, {"date_to": "2024-02-02"}, 1),
        ]
    )
    def test_date_range(self, f1, f2, num_keys):
        q1 = TrendsQuery(**base_funnel, dateRange=f1)
        q2 = TrendsQuery(**base_funnel, dateRange=f2)

        self._assert_filter("dateRange", num_keys, q1, q2)

    @parameterized.expand(
        [
            # general: missing filter
            (None, {}, 0),
            ({}, {"display": "ActionsLineGraph"}, 0),
            ({"display": "ActionsAreaGraph"}, {"display": "ActionsAreaGraph"}, 1),
        ]
    )
    def test_trends_filter(self, f1, f2, num_keys):
        q1 = TrendsQuery(**base_funnel, trendsFilter=f1)
        q2 = TrendsQuery(**base_funnel, trendsFilter=f2)

        self._assert_filter("trendsFilter", num_keys, q1, q2)

    @parameterized.expand(
        [
            # general: missing filter
            (None, {}, 0),
            # general: ordering of keys
            (
                {"funnelVizType": FunnelVizType.time_to_convert, "funnelOrderType": StepOrderValue.strict},
                {"funnelOrderType": StepOrderValue.strict, "funnelVizType": FunnelVizType.time_to_convert},
                2,
            ),
            # binCount
            # ({}, {"binCount": 4}, 0),
            (
                {"binCount": 4, "funnelVizType": FunnelVizType.time_to_convert},
                {"binCount": 4, "funnelVizType": FunnelVizType.time_to_convert},
                2,
            ),
            # breakdownAttributionType
            ({}, {"breakdownAttributionType": BreakdownAttributionType.first_touch}, 0),
            (
                {"breakdownAttributionType": BreakdownAttributionType.last_touch},
                {"breakdownAttributionType": BreakdownAttributionType.last_touch},
                1,
            ),
            # breakdownAttributionValue
            # ({}, {"breakdownAttributionValue": 2}, 0),
            (
                {"breakdownAttributionType": BreakdownAttributionType.step, "breakdownAttributionValue": 2},
                {"breakdownAttributionType": BreakdownAttributionType.step, "breakdownAttributionValue": 2},
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
            ({}, {"funnelOrderType": StepOrderValue.ordered}, 0),
            ({"funnelOrderType": StepOrderValue.strict}, {"funnelOrderType": StepOrderValue.strict}, 1),
            # funnelStepReference
            ({}, {"funnelStepReference": FunnelStepReference.total}, 0),
            (
                {"funnelStepReference": FunnelStepReference.previous},
                {"funnelStepReference": FunnelStepReference.previous},
                1,
            ),
            # funnelVizType
            ({}, {"funnelVizType": FunnelVizType.steps}, 0),
            ({"funnelVizType": FunnelVizType.trends}, {"funnelVizType": FunnelVizType.trends}, 1),
            # funnelWindowInterval
            ({}, {"funnelWindowInterval": 14}, 0),
            ({"funnelWindowInterval": 12}, {"funnelWindowInterval": 12}, 1),
            # funnelWindowIntervalUnit
            ({}, {"funnelWindowIntervalUnit": FunnelConversionWindowTimeUnit.day}, 0),
            (
                {"funnelWindowIntervalUnit": FunnelConversionWindowTimeUnit.week},
                {"funnelWindowIntervalUnit": FunnelConversionWindowTimeUnit.week},
                1,
            ),
            # hidden_legend_breakdowns
            # ({}, {"hidden_legend_breakdowns": []}, 0),
            # layout
            ({}, {"layout": FunnelLayout.vertical}, 0),
            ({"layout": FunnelLayout.horizontal}, {"layout": FunnelLayout.horizontal}, 1),
        ]
    )
    def test_funnels_filter(self, f1, f2, num_keys):
        q1 = FunnelsQuery(**base_funnel, funnelsFilter=f1)
        q2 = FunnelsQuery(**base_funnel, funnelsFilter=f2)

        self._assert_filter("funnelsFilter", num_keys, q1, q2)
