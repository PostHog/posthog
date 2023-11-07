from typing import cast
from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.insights.trends.aggregation_operations import QueryAlternator


class TestQueryAlternator:
    def test_select(self):
        query = parse_select("SELECT event from events")

        query_modifier = QueryAlternator(query)
        query_modifier.append_select(ast.Field(chain=["test"]))
        query_modifier.build()

        assert len(query.select) == 2
        assert cast(ast.Field, query.select[1]).chain == ["test"]

    def test_group_no_pre_existing(self):
        query = parse_select("SELECT event from events")

        query_modifier = QueryAlternator(query)
        query_modifier.append_group_by(ast.Field(chain=["event"]))
        query_modifier.build()

        assert len(query.group_by) == 1
        assert cast(ast.Field, query.group_by[0]).chain == ["event"]

    def test_group_with_pre_existing(self):
        query = parse_select("SELECT event from events GROUP BY uuid")

        query_modifier = QueryAlternator(query)
        query_modifier.append_group_by(ast.Field(chain=["event"]))
        query_modifier.build()

        assert len(query.group_by) == 2
        assert cast(ast.Field, query.group_by[0]).chain == ["uuid"]
        assert cast(ast.Field, query.group_by[1]).chain == ["event"]

    def test_replace_select_from(self):
        query = parse_select("SELECT event from events")

        query_modifier = QueryAlternator(query)
        query_modifier.replace_select_from(ast.JoinExpr(table=ast.Field(chain=["groups"])))
        query_modifier.build()

        assert query.select_from.table.chain == ["groups"]
