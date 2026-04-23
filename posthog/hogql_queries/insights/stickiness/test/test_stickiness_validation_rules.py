from unittest import TestCase
from unittest.mock import MagicMock

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import EventsNode, StickinessCriteria, StickinessFilter, StickinessOperator, StickinessQuery

from posthog.hogql_queries.insights.stickiness.stickiness_validation_rules import (
    STICKINESS_CRITERIA_ZERO_INCOMPATIBLE_CODE,
    ValidateStickinessCriteria,
)
from posthog.hogql_queries.validation.validation import QueryValidationContext


class TestStickinessValidationRules(TestCase):
    def _context(self, query: StickinessQuery) -> QueryValidationContext[StickinessQuery]:
        team = MagicMock()
        runner = MagicMock(query=query, team=team, user=None)
        return QueryValidationContext(query=query, team=team, user=None, runner=runner)

    def test_schema_allows_persisted_zero_value(self) -> None:
        StickinessCriteria(operator=StickinessOperator.GTE, value=0)
        StickinessCriteria(operator=StickinessOperator.EXACT, value=0)
        StickinessCriteria(operator=StickinessOperator.LTE, value=0)

    def test_schema_rejects_negative_value(self) -> None:
        with self.assertRaises(Exception):
            StickinessCriteria(operator=StickinessOperator.GTE, value=-1)

    @parameterized.expand(
        [
            ("exact_zero", StickinessOperator.EXACT),
            ("lte_zero", StickinessOperator.LTE),
        ]
    )
    def test_rejects_zero_with_incompatible_operator(self, _name: str, operator: StickinessOperator) -> None:
        query = StickinessQuery(
            series=[EventsNode(event="$pageview")],
            stickinessFilter=StickinessFilter(stickinessCriteria=StickinessCriteria(operator=operator, value=0)),
        )

        with self.assertRaises(ValidationError) as context:
            ValidateStickinessCriteria().validate(self._context(query))

        self.assertIn(
            "Stickiness criteria with operator exact or lte must use a value greater than 0.",
            str(context.exception),
        )
        self.assertEqual(context.exception.get_codes(), [STICKINESS_CRITERIA_ZERO_INCOMPATIBLE_CODE])

    def test_allows_zero_with_gte(self) -> None:
        query = StickinessQuery(
            series=[EventsNode(event="$pageview")],
            stickinessFilter=StickinessFilter(
                stickinessCriteria=StickinessCriteria(operator=StickinessOperator.GTE, value=0)
            ),
        )

        ValidateStickinessCriteria().validate(self._context(query))

    def test_allows_non_zero_values(self) -> None:
        for operator in (StickinessOperator.GTE, StickinessOperator.LTE, StickinessOperator.EXACT):
            query = StickinessQuery(
                series=[EventsNode(event="$pageview")],
                stickinessFilter=StickinessFilter(stickinessCriteria=StickinessCriteria(operator=operator, value=3)),
            )
            ValidateStickinessCriteria().validate(self._context(query))

    def test_allows_missing_criteria(self) -> None:
        query = StickinessQuery(series=[EventsNode(event="$pageview")])
        ValidateStickinessCriteria().validate(self._context(query))

        query_with_empty_filter = StickinessQuery(
            series=[EventsNode(event="$pageview")],
            stickinessFilter=StickinessFilter(),
        )
        ValidateStickinessCriteria().validate(self._context(query_with_empty_filter))
