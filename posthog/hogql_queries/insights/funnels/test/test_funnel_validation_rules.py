from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    EventsNode,
    FunnelExclusionEventsNode,
    FunnelsFilter,
    FunnelsQuery,
    FunnelVizType,
    StepOrderValue,
)

from posthog.hogql_queries.insights.funnels.funnel_validation_rules import (
    RequireAtLeastTwoFunnelSteps,
    ValidateFunnelExclusions,
    ValidateFunnelStepRange,
    ValidateOptionalFunnelSteps,
)
from posthog.hogql_queries.validation.validation import QueryValidationContext


class TestFunnelValidationRules(BaseTest):
    def _context(self, query: FunnelsQuery) -> QueryValidationContext:
        runner = MagicMock(query=query, team=self.team, user=None)
        return QueryValidationContext(query=query, team=self.team, user=None, runner=runner)

    def test_requires_at_least_two_funnel_steps(self):
        query = FunnelsQuery(series=[EventsNode(event="$pageview")])

        with self.assertRaises(ValidationError) as context:
            RequireAtLeastTwoFunnelSteps().validate(self._context(query))

        self.assertIn("Funnels require at least two steps.", str(context.exception))
        self.assertEqual(context.exception.get_codes(), ["funnels_require_at_least_two_steps"])

    @parameterized.expand(
        [
            (
                "from_step_out_of_bounds",
                FunnelsFilter(funnelFromStep=2),
                "funnelFromStep is out of bounds. It must be between 0 and 1.",
            ),
            (
                "to_step_out_of_bounds",
                FunnelsFilter(funnelToStep=3),
                "funnelToStep is out of bounds. It must be between 1 and 2.",
            ),
            (
                "reversed_range",
                FunnelsFilter(funnelFromStep=1, funnelToStep=1),
                "Funnel step range is invalid. funnelToStep should be greater than funnelFromStep.",
            ),
        ]
    )
    def test_validates_funnel_step_range(self, _name, funnels_filter, expected_error):
        query = FunnelsQuery(
            series=[EventsNode(event="step 1"), EventsNode(event="step 2"), EventsNode(event="step 3")],
            funnelsFilter=funnels_filter,
        )

        with self.assertRaises(ValidationError) as context:
            ValidateFunnelStepRange().validate(self._context(query))

        self.assertIn(expected_error, str(context.exception))
        self.assertEqual(context.exception.get_codes(), ["funnel_step_range_invalid"])

    @parameterized.expand(
        [
            (
                "same_step_range",
                FunnelExclusionEventsNode(event="exclude", funnelFromStep=1, funnelToStep=1),
                "Exclusion event range is invalid. End of range should be greater than start.",
            ),
            (
                "start_step_out_of_range",
                FunnelExclusionEventsNode(event="exclude", funnelFromStep=2, funnelToStep=3),
                "Exclusion event range is invalid. Start of range is greater than number of steps.",
            ),
            (
                "end_step_out_of_range",
                FunnelExclusionEventsNode(event="exclude", funnelFromStep=0, funnelToStep=3),
                "Exclusion event range is invalid. End of range is greater than number of steps.",
            ),
        ]
    )
    def test_validates_funnel_exclusion_ranges(self, _name, exclusion, expected_error):
        query = FunnelsQuery(
            series=[EventsNode(event="step 1"), EventsNode(event="step 2"), EventsNode(event="step 3")],
            funnelsFilter=FunnelsFilter(exclusions=[exclusion]),
        )

        with self.assertRaises(ValidationError) as context:
            ValidateFunnelExclusions().validate(self._context(query))

        self.assertIn(expected_error, str(context.exception))
        self.assertEqual(context.exception.get_codes(), ["funnel_exclusions_invalid"])

    def test_disallows_exclusion_that_matches_funnel_step(self):
        query = FunnelsQuery(
            series=[EventsNode(event="step 1"), EventsNode(event="step 2")],
            funnelsFilter=FunnelsFilter(
                exclusions=[FunnelExclusionEventsNode(event="step 2", funnelFromStep=0, funnelToStep=1)]
            ),
        )

        with self.assertRaises(ValidationError) as context:
            ValidateFunnelExclusions().validate(self._context(query))

        self.assertIn("Exclusion steps cannot contain an event that's part of funnel steps.", str(context.exception))
        self.assertEqual(context.exception.get_codes(), ["funnel_exclusions_invalid"])

    @parameterized.expand(
        [
            (
                "unsupported_feature_combination",
                FunnelsQuery(
                    series=[EventsNode(event="step 1"), EventsNode(event="step 2", optionalInFunnel=True)],
                    funnelsFilter=FunnelsFilter(
                        funnelVizType=FunnelVizType.TRENDS,
                        funnelOrderType=StepOrderValue.ORDERED,
                    ),
                ),
                'Optional funnel steps are only supported in funnels with step order Sequential or Strict and the graph type "Conversion Steps".',
            ),
            (
                "first_step_optional",
                FunnelsQuery(
                    series=[EventsNode(event="step 1", optionalInFunnel=True), EventsNode(event="step 2")],
                ),
                "The first step of a funnel cannot be optional.",
            ),
            (
                "optional_step_matches_following_required_step",
                FunnelsQuery(
                    series=[
                        EventsNode(event="step 1"),
                        EventsNode(event="step 2", optionalInFunnel=True),
                        EventsNode(event="step 2"),
                    ],
                ),
                "An optional step cannot be the same as the following required step.",
            ),
        ]
    )
    def test_validates_optional_funnel_steps(self, _name, query, expected_error):
        with self.assertRaises(ValidationError) as context:
            ValidateOptionalFunnelSteps().validate(self._context(query))

        self.assertIn(expected_error, str(context.exception))
        self.assertEqual(context.exception.get_codes(), ["funnel_optional_steps_invalid"])
