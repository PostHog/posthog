from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from rest_framework.exceptions import ValidationError

from posthog.schema import EventsNode, LifecycleQuery

from posthog.hogql_queries.validation.rules import RequireAtLeastOneSeries
from posthog.hogql_queries.validation.validation import QueryValidationContext


class TestRequireAtLeastOneSeries(BaseTest):
    def _context(self, query: LifecycleQuery) -> QueryValidationContext:
        runner = MagicMock(query=query, team=self.team, user=None)
        return QueryValidationContext(query=query, team=self.team, user=None, runner=runner)

    def test_raises_for_empty_series(self):
        query = LifecycleQuery(series=[])

        with self.assertRaises(ValidationError) as context:
            RequireAtLeastOneSeries().validate(self._context(query))

        self.assertIn("Lifecycle insights require at least one series.", str(context.exception))

    def test_allows_non_empty_series(self):
        query = LifecycleQuery(series=[EventsNode(event="$pageview")])

        RequireAtLeastOneSeries().validate(self._context(query))
