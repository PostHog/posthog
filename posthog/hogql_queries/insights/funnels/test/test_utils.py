from typing import Any

from django.test import SimpleTestCase

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import clone_expr

from posthog.hogql_queries.insights.funnels.test.test_funnel_persons import get_actors_legacy_filters
from posthog.hogql_queries.insights.funnels.utils import alias_columns_in_select
from posthog.models.team.team import Team


class TestUtils(SimpleTestCase):
    def test_alias_columns_in_select(self):
        sql = """
        SELECT
            e.timestamp AS timestamp,
            person_id AS aggregation_target,
            if(event = '$pageview' and properties.$browser = 'Opera', 1, 0) AS step_0,
            0 as step_1
        """
        query = parse_select(sql)
        assert isinstance(query, ast.SelectQuery)

        result = alias_columns_in_select(query.select, table_alias="my_table")
        result = [clone_expr(r, clear_locations=True) for r in result]  # remove locations from ast for easier asserts

        assert len(result) == 4
        assert result[0] == ast.Alias(alias="timestamp", expr=ast.Field(chain=["my_table", "timestamp"]))
        assert result[1] == ast.Alias(
            alias="aggregation_target", expr=ast.Field(chain=["my_table", "aggregation_target"])
        )
        assert result[2] == ast.Alias(alias="step_0", expr=ast.Field(chain=["my_table", "step_0"]))
        assert result[3] == ast.Alias(alias="step_1", expr=ast.Field(chain=["my_table", "step_1"]))


class PseudoFunnelActors:
    def __init__(self, person_filter: Any, team: Team):
        self.filters = person_filter._data
        self.team = team

    def get_actors(self):
        actors = get_actors_legacy_filters(
            self.filters,
            self.team,
            funnel_step=self.filters.get("funnel_step"),
            funnel_step_breakdown=self.filters.get("funnel_step_breakdown"),
        )

        return (
            None,
            [{"id": actor[0]} for actor in actors],
            None,
        )
