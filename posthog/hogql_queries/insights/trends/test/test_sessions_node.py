from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.core.exceptions import ValidationError
from django.test import override_settings

from posthog.schema import (
    BaseMathType,
    DateRange,
    EventsNode,
    SessionsNode,
    TrendsFilter,
    TrendsFormulaNode,
    TrendsQuery,
)

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner


@override_settings(IN_UNIT_TESTING=True)
class TestSessionsNode(ClickhouseTestMixin, APIBaseTest):
    def test_basic_sessions_query(self) -> None:
        query = TrendsQuery(
            series=[SessionsNode(math=BaseMathType.TOTAL)],
            dateRange=DateRange(date_from="-7d"),
        )

        runner = TrendsQueryRunner(query=query, team=self.team)
        response = runner.calculate()

        assert response is not None
        assert len(response.results) == 1

    def test_sessions_with_name(self) -> None:
        query = TrendsQuery(
            series=[SessionsNode(name="My Sessions", math=BaseMathType.TOTAL)],
            dateRange=DateRange(date_from="-7d"),
        )

        runner = TrendsQueryRunner(query=query, team=self.team)
        response = runner.calculate()

        assert response is not None
        assert len(response.results) == 1
        assert response.results[0].get("label") == "My Sessions"

    def test_cannot_mix_sessions_with_events(self) -> None:
        query = TrendsQuery(
            series=[
                SessionsNode(math=BaseMathType.TOTAL),
                EventsNode(event="$pageview"),
            ],
            dateRange=DateRange(date_from="-7d"),
        )

        with self.assertRaises(ValidationError) as context:
            TrendsQueryRunner(query=query, team=self.team)

        assert "Cannot mix SessionsNode" in str(context.exception)

    def test_sessions_with_formulas_not_allowed(self) -> None:
        query = TrendsQuery(
            series=[SessionsNode(math=BaseMathType.TOTAL)],
            dateRange=DateRange(date_from="-7d"),
            trendsFilter=TrendsFilter(formulaNodes=[TrendsFormulaNode(formula="A + B")]),
        )

        with self.assertRaises(ValidationError) as context:
            TrendsQueryRunner(query=query, team=self.team)

        assert "Formulas are not supported" in str(context.exception)
