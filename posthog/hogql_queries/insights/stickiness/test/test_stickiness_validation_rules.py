from unittest import TestCase
from unittest.mock import MagicMock

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import EventsNode, StickinessFilter, StickinessQuery

from posthog.hogql_queries.insights.stickiness.stickiness_validation_rules import (
    MAX_INTERVAL_COUNT,
    STICKINESS_CRITERIA_NEGATIVE_CODE,
    STICKINESS_CRITERIA_ZERO_INCOMPATIBLE_CODE,
    STICKINESS_INTERVAL_COUNT_NON_POSITIVE_CODE,
    STICKINESS_INTERVAL_COUNT_TOO_LARGE_CODE,
    ValidateIntervalCount,
    ValidateStickinessCriteria,
)
from posthog.hogql_queries.validation.validation import QueryValidationContext


class TestStickinessValidationRules(TestCase):
    def _context(self, query: StickinessQuery) -> QueryValidationContext[StickinessQuery]:
        team = MagicMock()
        runner = MagicMock(query=query, team=team, user=None)
        return QueryValidationContext(query=query, team=team, user=None, runner=runner)

    @parameterized.expand(
        [
            (
                "negative_value",
                StickinessFilter(stickinessCriteria={"operator": "gte", "value": -1}),
                "Stickiness criteria value must be non-negative.",
                STICKINESS_CRITERIA_NEGATIVE_CODE,
            ),
            (
                "exact_zero",
                StickinessFilter(stickinessCriteria={"operator": "exact", "value": 0}),
                "Stickiness criteria with operator exact or lte must use a value greater than 0.",
                STICKINESS_CRITERIA_ZERO_INCOMPATIBLE_CODE,
            ),
            (
                "lte_zero",
                StickinessFilter(stickinessCriteria={"operator": "lte", "value": 0}),
                "Stickiness criteria with operator exact or lte must use a value greater than 0.",
                STICKINESS_CRITERIA_ZERO_INCOMPATIBLE_CODE,
            ),
        ]
    )
    def test_rejects_invalid_stickiness_criteria(
        self, _name: str, filters: StickinessFilter, expected_error: str, expected_code: str
    ):
        query = StickinessQuery(series=[EventsNode(event="$pageview")], stickinessFilter=filters)

        with self.assertRaises(ValidationError) as context:
            ValidateStickinessCriteria().validate(self._context(query))

        self.assertIn(expected_error, str(context.exception))
        self.assertEqual(context.exception.get_codes(), [expected_code])

    def test_allows_zero_for_gte_stickiness_criteria(self):
        query = StickinessQuery(
            series=[EventsNode(event="$pageview")],
            stickinessFilter=StickinessFilter(stickinessCriteria={"operator": "gte", "value": 0}),
        )

        ValidateStickinessCriteria().validate(self._context(query))

    @parameterized.expand(
        [
            ("zero", 0, "intervalCount must be a positive integer.", STICKINESS_INTERVAL_COUNT_NON_POSITIVE_CODE),
            (
                "negative",
                -1,
                "intervalCount must be a positive integer.",
                STICKINESS_INTERVAL_COUNT_NON_POSITIVE_CODE,
            ),
            (
                "above_max",
                MAX_INTERVAL_COUNT + 1,
                f"intervalCount cannot exceed {MAX_INTERVAL_COUNT}.",
                STICKINESS_INTERVAL_COUNT_TOO_LARGE_CODE,
            ),
        ]
    )
    def test_rejects_invalid_interval_count(
        self, _name: str, interval_count: int, expected_error: str, expected_code: str
    ):
        query = StickinessQuery(series=[EventsNode(event="$pageview")], intervalCount=interval_count)

        with self.assertRaises(ValidationError) as context:
            ValidateIntervalCount().validate(self._context(query))

        self.assertIn(expected_error, str(context.exception))
        self.assertEqual(context.exception.get_codes(), [expected_code])

    def test_allows_valid_interval_count(self):
        query = StickinessQuery(series=[EventsNode(event="$pageview")], intervalCount=MAX_INTERVAL_COUNT)

        ValidateIntervalCount().validate(self._context(query))
