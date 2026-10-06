from typing import Optional

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import (
    BIVisualizationNode,
    BreakdownFilter,
    DashboardFilter,
    DateRange,
    EventPropertyFilter,
    HogQLFilters,
    HogQLQuery,
    IntervalType,
)

from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import prepare_and_print_ast

from posthog.hogql_queries.apply_dashboard_filters import (
    apply_dashboard_filters,
    apply_dashboard_filters_to_dict,
    apply_dashboard_variables,
    apply_dashboard_variables_to_dict,
)
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner


class TestHogQLDashboardFilters(BaseTest):
    @parameterized.expand([("dict", True), ("model", False)])
    def test_bi_wrapper_preserved_when_applying_filters_and_variables(self, _name: str, as_dict: bool) -> None:
        worksheet = BIVisualizationNode.model_validate(
            {
                "kind": "BIVisualizationNode",
                "config": {
                    "chartType": "ActionsBar",
                    "columns": [],
                    "rows": [],
                    "values": [],
                    "filters": [],
                    "limit": 100,
                },
                "source": {
                    "kind": "HogQLQuery",
                    "query": "SELECT {variables.plan} FROM events WHERE {filters}",
                    "variables": {"plan": {"variableId": "plan", "code_name": "plan", "value": "starter"}},
                },
            }
        )
        variables = {"plan": {"value": "enterprise"}}
        filters = DashboardFilter(date_from="-30d", properties=[EventPropertyFilter(key="plan", value="enterprise")])
        if as_dict:
            updated_dict = apply_dashboard_filters_to_dict(worksheet.model_dump(), filters.model_dump(), self.team)
            updated_dict = apply_dashboard_variables_to_dict(updated_dict, variables, self.team)
            updated = BIVisualizationNode.model_validate(updated_dict)
        else:
            updated = apply_dashboard_filters(worksheet, filters, self.team)
            updated = apply_dashboard_variables(updated, variables, self.team)
        assert updated.config == worksheet.config
        assert updated.source.filters is not None
        assert updated.source.filters.dateRange is not None
        assert updated.source.filters.dateRange.date_from == "-30d"
        assert updated.source.filters.properties == filters.properties
        assert updated.source.variables is not None
        assert updated.source.variables["plan"].value == "enterprise"
        assert updated.source.variables["plan"].code_name == "plan"

    @parameterized.expand(
        [
            ("native", "{filters}"),
            ("bound", "{filters(timestamp AS timestamp, properties.plan AS 'plan')}"),
        ]
    )
    def test_bi_dashboard_filters_reach_the_query(self, _name: str, placeholder: str) -> None:
        runner = self._create_hogql_runner(
            query="SELECT count() FROM events WHERE " + placeholder + " AND event = 'purchase'",
            filters=HogQLFilters(dateRange=DateRange(date_from="-7d")),
        )
        runner.apply_dashboard_filters(
            DashboardFilter(
                date_from="2026-01-01",
                date_to="2026-01-31",
                properties=[EventPropertyFilter(key="plan", value="pro", operator="exact")],
            )
        )
        sql = prepare_and_print_ast(
            runner.to_query(), dialect="hogql", context=HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        )[0]
        assert "2026-01-01" in sql
        assert "2026-01-31" in sql
        assert "plan" in sql and "'pro'" in sql
        assert "equals(event, 'purchase')" in sql
        assert "{filters" not in sql

    def _create_hogql_runner(
        self, query: str = "SELECT uuid FROM events", filters: Optional[HogQLFilters] = None
    ) -> HogQLQueryRunner:
        return HogQLQueryRunner(team=self.team, query=HogQLQuery(query=query, filters=filters))

    def test_empty_dashboard_filters_change_nothing(self):
        query_runner = self._create_hogql_runner()
        query_runner.apply_dashboard_filters(DashboardFilter())

        assert query_runner.query.filters == HogQLFilters()

    def test_date_from_override_updates_whole_date_range(self):
        query_runner = self._create_hogql_runner()
        query_runner.apply_dashboard_filters(DashboardFilter(date_from="-14d"))

        assert query_runner.query.filters == HogQLFilters(dateRange=DateRange(date_from="-14d", date_to=None))

    def test_date_from_and_date_to_override_updates_whole_date_range(self):
        query_runner = self._create_hogql_runner(
            filters=HogQLFilters(dateRange=DateRange(date_from="-7d", date_to=None))
        )
        query_runner.apply_dashboard_filters(DashboardFilter(date_from="2024-07-07", date_to="2024-07-14"))

        assert query_runner.query.filters == HogQLFilters(
            dateRange=DateRange(date_from="2024-07-07", date_to="2024-07-14")
        )

    def test_properties_set_when_no_filters_present(self):
        query_runner = self._create_hogql_runner()
        query_runner.apply_dashboard_filters(
            DashboardFilter(properties=[EventPropertyFilter(key="key", value="value", operator="exact")])
        )

        assert query_runner.query.filters == HogQLFilters(
            properties=[EventPropertyFilter(key="key", value="value", operator="exact")]
        )

    def test_properties_list_extends_filters_list(self):
        query_runner = self._create_hogql_runner(
            filters=HogQLFilters(properties=[EventPropertyFilter(key="abc", value="foo", operator="regex")])
        )
        query_runner.apply_dashboard_filters(
            DashboardFilter(properties=[EventPropertyFilter(key="xyz", value="bar", operator="regex")])
        )

        assert query_runner.query.filters == HogQLFilters(
            properties=[
                EventPropertyFilter(key="abc", value="foo", operator="regex"),
                EventPropertyFilter(key="xyz", value="bar", operator="regex"),
            ]
        )

    def test_interval_is_copied_for_the_interval_placeholder(self):
        query_runner = self._create_hogql_runner()
        query_runner.apply_dashboard_filters(DashboardFilter(interval=IntervalType.WEEK))

        assert query_runner.query.filters == HogQLFilters(interval=IntervalType.WEEK)

    def test_breakdown_filter_is_copied_for_the_breakdown_placeholder(self):
        breakdown_filter = BreakdownFilter(breakdown="plan", breakdown_type="event")
        query_runner = self._create_hogql_runner()
        query_runner.apply_dashboard_filters(DashboardFilter(breakdown_filter=breakdown_filter))

        assert query_runner.query.filters == HogQLFilters(breakdownFilter=breakdown_filter)

    @parameterized.expand(
        [
            ("force_on", None, True, True),
            ("force_off_overrides_insight", True, False, False),
            ("absent_inherits_insight", True, None, True),
        ]
    )
    def test_filter_test_accounts_tri_state_override(
        self, _name: str, insight_value: Optional[bool], override: Optional[bool], expected: Optional[bool]
    ):
        query_runner = self._create_hogql_runner(filters=HogQLFilters(filterTestAccounts=insight_value))
        query_runner.apply_dashboard_filters(DashboardFilter(filterTestAccounts=override))

        assert query_runner.query.filters == HogQLFilters(filterTestAccounts=expected)
