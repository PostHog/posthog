import json
from typing import Optional, Any
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext, MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY, HogQLGlobalSettings
from posthog.hogql.hogqlx import convert_to_hx
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.utils import dump_with_kind
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.models import Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import HogQLQueryModifiers, InsightVizNode, InsightVizNodeResponse


class InsightVizNodeRunner(QueryRunner):
    query: InsightVizNode

    def __init__(
        self,
        query: InsightVizNode | dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
        query_id: Optional[str] = None,
    ):
        super().__init__(
            query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            query_id=query_id,
            extract_modifiers=lambda query: query.source.modifiers if hasattr(query.source, "modifiers") else None,
        )

    @cached_property
    def source_runner(self) -> QueryRunner:
        return get_query_runner(self.query.source, self.team, self.timings, self.limit_context, self.modifiers)

    @cached_property
    def source_type(self) -> str:
        return (
            self.source_runner.query.kind
            if hasattr(self.source_runner.query, "kind")
            else str(self.source_runner.query)
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        source_query = self.source_runner.to_query()
        input_query_json = json.dumps(dump_with_kind(self.query))

        if isinstance(source_query, ast.SelectSetQuery):  # and source_query.select_queries == 1:
            # KLUDGE
            source_query = source_query.initial_select_query

        if isinstance(source_query, ast.SelectQuery):
            # convert to ['__hx_tag', 'InsightViz', '__hx_insight': 'TrendsQuery', 'date', '...', 'step', '...', ...]
            new_select = [
                ast.Constant(value="__hx_tag"),
                ast.Constant(value="__hx_obj"),
            ]
            select_expr = ast.Tuple(
                exprs=[
                    ast.Constant(value="__hx_tag"),
                    ast.Constant(value="__hx_obj"),
                ]
            )
            for expr in source_query.select:
                random_string = str(expr)
                if isinstance(expr, ast.Alias):
                    new_select.append(expr)
                    select_expr.exprs.append(ast.Constant(value=expr.alias))
                    select_expr.exprs.append(ast.Field(chain=["source", expr.alias]))
                else:
                    new_select.append(ast.Alias(alias=random_string, expr=expr))
                    select_expr.exprs.append(ast.Constant(value=random_string))
                    select_expr.exprs.append(ast.Field(chain=["source", random_string]))
            source_query.select = new_select

            viz_node_tuple = ast.Tuple(
                exprs=[
                    ast.Constant(value="__hx_tag"),
                    ast.Constant(value="InsightVizNode"),
                    ast.Constant(value="insight"),
                    ast.Constant(value=self.source_type),
                    ast.Constant(value="results"),
                    select_expr,
                    ast.Constant(value="query"),
                    convert_to_hx(input_query_json),
                ]
            )

            return ast.SelectQuery(
                select=[ast.Alias(alias=self.source_type, expr=viz_node_tuple)],
                select_from=ast.JoinExpr(alias="source", table=source_query),
            )
        elif isinstance(source_query, ast.SelectSetQuery):
            # convert to ['__hx_tag', 'InsightViz', '__hx_insight': 'TrendsQuery', 'date', '...', 'step', '...', ...]
            for q in source_query.select_queries():
                q.select = [
                    ast.Alias(alias="__hx_insight_viz", expr=ast.Constant(value=self.source_type)),
                    *q.select,
                ]
            return source_query

        raise ValueError(f"Unsupported source query type: {type(source_query)}")

    def calculate(self) -> InsightVizNodeResponse:
        query = self.to_query()

        response = execute_hogql_query(
            query_type=self.source_type,
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            settings=HogQLGlobalSettings(
                max_bytes_before_external_group_by=MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY
            ),  # Make sure funnel queries never OOM
        )

        response.results = self.validate_results(response.results)
