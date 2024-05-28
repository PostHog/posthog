import json
from typing import Any
from parameterized import parameterized

from django.test.testcases import TestCase

from posthog.schema import (
    FunnelConversionWindowTimeUnit,
    FunnelExclusionEventsNode,
    FunnelStepReference,
    FunnelsQuery,
    FunnelVizType,
    FunnelLayout,
    StepOrderValue,
    BreakdownAttributionType,
)
from posthog.schema_helpers import to_json


base_funnel: dict[str, Any] = {"series": []}


class TestSchemaHelpers(TestCase):
    maxDiff = None

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
            ({}, {"binCount": 4}, 0),
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
            ({}, {"breakdownAttributionValue": 2}, 0),
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
            ({}, {"funnelAggregateByHogQL": ""}, 0),
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
            ({}, {"hidden_legend_breakdowns": []}, 0),
            # layout
            ({}, {"layout": FunnelLayout.vertical}, 0),
            ({"layout": FunnelLayout.horizontal}, {"layout": FunnelLayout.horizontal}, 1),
        ]
    )
    def test_clean_query_funnel_filter(self, f1, f2, num_keys):
        q1 = FunnelsQuery(**base_funnel, funnelsFilter=f1)
        q2 = FunnelsQuery(**base_funnel, funnelsFilter=f2)

        self.assertEqual(to_json(q1), to_json(q2))
        self.assertEqual(num_keys, len(json.loads(to_json(q1))["funnelsFilter"].keys()))
