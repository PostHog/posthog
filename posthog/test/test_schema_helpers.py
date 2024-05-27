import json
from typing import Any
from parameterized import parameterized

from django.test.testcases import TestCase

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
    RetentionQuery,
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

    @parameterized.expand(
        [
            ({}, {"date_from": "-7d", "explicitDate": False}, 2),
        ]
    )
    def test_date_range(self, f1, f2, num_keys):
        q1 = TrendsQuery(**base_funnel, dateRange=f1)
        q2 = TrendsQuery(**base_funnel, dateRange=f2)

        self.assertEqual(to_json(q1), to_json(q2))
        self.assertEqual(num_keys, len(json.loads(to_json(q1))["dateRange"].keys()))

    @parameterized.expand(
        [
            # general: missing filter
            (None, {}, 7),
        ]
    )
    def test_trends_filter(self, f1, f2, num_keys):
        q1 = TrendsQuery(**base_funnel, trendsFilter=f1)
        q2 = TrendsQuery(**base_funnel, trendsFilter=f2)

        self.assertEqual(to_json(q1), to_json(q2))
        self.assertEqual(num_keys, len(json.loads(to_json(q1))["trendsFilter"].keys()))

    @parameterized.expand(
        [
            # general: missing filter
            (None, {}, 8),
            # general: ordering of keys
            (
                {"funnelVizType": FunnelVizType.time_to_convert, "funnelOrderType": StepOrderValue.strict},
                {"funnelOrderType": StepOrderValue.strict, "funnelVizType": FunnelVizType.time_to_convert},
                8,
            ),
            # binCount
            # ({}, {"binCount": 4}, 8),
            (
                {"binCount": 4, "funnelVizType": FunnelVizType.time_to_convert},
                {"binCount": 4, "funnelVizType": FunnelVizType.time_to_convert},
                9,
            ),
            # breakdownAttributionType
            ({}, {"breakdownAttributionType": BreakdownAttributionType.first_touch}, 8),
            (
                {"breakdownAttributionType": BreakdownAttributionType.last_touch},
                {"breakdownAttributionType": BreakdownAttributionType.last_touch},
                8,
            ),
            # breakdownAttributionValue
            # ({}, {"breakdownAttributionValue": 2}, 8),
            (
                {"breakdownAttributionType": BreakdownAttributionType.step, "breakdownAttributionValue": 2},
                {"breakdownAttributionType": BreakdownAttributionType.step, "breakdownAttributionValue": 2},
                9,
            ),
            # exclusions
            ({}, {"exclusions": []}, 8),
            (
                {"exclusions": [FunnelExclusionEventsNode(funnelFromStep=0, funnelToStep=1)]},
                {"exclusions": [FunnelExclusionEventsNode(funnelFromStep=0, funnelToStep=1)]},
                8,
            ),
            # funnelAggregateByHogQL
            # ({}, {"funnelAggregateByHogQL": ""}, 8),
            ({"funnelAggregateByHogQL": "distinct_id"}, {"funnelAggregateByHogQL": "distinct_id"}, 9),
            # funnelFromStep and funnelToStep
            ({"funnelFromStep": 1, "funnelToStep": 2}, {"funnelFromStep": 1, "funnelToStep": 2}, 10),
            # funnelOrderType
            ({}, {"funnelOrderType": StepOrderValue.ordered}, 8),
            ({"funnelOrderType": StepOrderValue.strict}, {"funnelOrderType": StepOrderValue.strict}, 8),
            # funnelStepReference
            ({}, {"funnelStepReference": FunnelStepReference.total}, 8),
            (
                {"funnelStepReference": FunnelStepReference.previous},
                {"funnelStepReference": FunnelStepReference.previous},
                8,
            ),
            # funnelVizType
            ({}, {"funnelVizType": FunnelVizType.steps}, 8),
            ({"funnelVizType": FunnelVizType.trends}, {"funnelVizType": FunnelVizType.trends}, 8),
            # funnelWindowInterval
            ({}, {"funnelWindowInterval": 14}, 8),
            ({"funnelWindowInterval": 12}, {"funnelWindowInterval": 12}, 8),
            # funnelWindowIntervalUnit
            ({}, {"funnelWindowIntervalUnit": FunnelConversionWindowTimeUnit.day}, 8),
            (
                {"funnelWindowIntervalUnit": FunnelConversionWindowTimeUnit.week},
                {"funnelWindowIntervalUnit": FunnelConversionWindowTimeUnit.week},
                8,
            ),
            # hidden_legend_breakdowns
            # ({}, {"hidden_legend_breakdowns": []}, 8),
            # layout
            ({}, {"layout": FunnelLayout.vertical}, 8),
            ({"layout": FunnelLayout.horizontal}, {"layout": FunnelLayout.horizontal}, 8),
        ]
    )
    def test_funnels_filter(self, f1, f2, num_keys):
        q1 = FunnelsQuery(**base_funnel, funnelsFilter=f1)
        q2 = FunnelsQuery(**base_funnel, funnelsFilter=f2)

        self.assertEqual(to_json(q1), to_json(q2))
        self.assertEqual(num_keys, len(json.loads(to_json(q1))["funnelsFilter"].keys()))

    @parameterized.expand(
        [
            # general: missing filter
            (None, {}, 7),
        ]
    )
    def test_retention_filter(self, f1, f2, num_keys):
        q1 = RetentionQuery(**base_funnel, retentionFilter=f1)
        q2 = RetentionQuery(**base_funnel, retentionFilter=f2)

        self.assertEqual(to_json(q1), to_json(q2))
        self.assertEqual(num_keys, len(json.loads(to_json(q1))["retentionFilter"].keys()))
