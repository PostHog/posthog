from posthog.test.base import BaseTest

from posthog.schema import EventsNode, TrendsQuery

from posthog.hogql import ast

from posthog.hogql_queries.insights.query_context import QueryContext
from posthog.hogql_queries.insights.utils.properties import Properties

VALID_FILTER = {"key": "$host", "type": "event", "value": "localhost", "operator": "exact"}
# References a cohort that doesn't exist — e.g. one deleted after being added to test_account_filters.
DELETED_COHORT_FILTER = {"key": "id", "type": "cohort", "value": 999999999}


class TestProperties(BaseTest):
    def _to_exprs(self, test_account_filters: list[dict]) -> list[ast.Expr]:
        self.team.test_account_filters = test_account_filters
        self.team.save()
        query = TrendsQuery(series=[EventsNode()], filterTestAccounts=True)
        context = QueryContext(query=query, team=self.team)
        return Properties(context).to_exprs()

    def test_skips_invalid_test_account_filter_but_keeps_valid_ones(self):
        # A single unresolvable test account filter must not fail the whole query — the valid
        # filters should still be applied so the insight can still exclude internal traffic.
        exprs = self._to_exprs([DELETED_COHORT_FILTER, VALID_FILTER])

        self.assertEqual(len(exprs), 1)

    def test_all_invalid_test_account_filters_yield_no_exprs(self):
        exprs = self._to_exprs([DELETED_COHORT_FILTER])

        self.assertEqual(exprs, [])
