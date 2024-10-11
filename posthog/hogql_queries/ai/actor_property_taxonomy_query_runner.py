from typing import Optional

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.ai.utils import TaxonomyCacheMixin
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    ActorPropertyTaxonomyQuery,
    ActorPropertyTaxonomyQueryResponse,
    CachedActorPropertyTaxonomyQueryResponse,
)


class ActorPropertyTaxonomyQueryRunner(QueryRunner, TaxonomyCacheMixin):
    query: ActorPropertyTaxonomyQuery
    response: ActorPropertyTaxonomyQueryResponse
    cached_response: CachedActorPropertyTaxonomyQueryResponse

    def calculate(self):
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team)

        response = execute_hogql_query(
            query_type="ActorPropertyTaxonomyQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        results = (
            {
                "sample_values": response.results[0][0],
                "sample_count": response.results[0][1],
            }
            if response.results
            else {
                "sample_values": [],
                "sample_count": 0,
            }
        )

        return ActorPropertyTaxonomyQueryResponse(
            results=results,
            timings=response.timings,
            hogql=hogql,
            modifiers=self.modifiers,
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        query = ast.SelectQuery(
            select=[
                ast.Call(name="groupArray", args=[ast.Field(chain=["prop"])], params=[ast.Constant(value=5)]),
                ast.Call(name="count", args=[]),
            ],
            select_from=ast.JoinExpr(table=self._get_subquery()),
        )

        return query

    @property
    def _origin(self) -> str:
        if self.query.type == "person":
            return "persons"
        return "groups"

    def _subquery_filter(self) -> Optional[ast.Expr]:
        if self.query.type == "group" and not isinstance(self.query.group_type_index, int):
            raise ExposedHogQLError("group_type_index must be an integer.")

        field_filter = ast.Call(
            name="isNotNull",
            args=[ast.Field(chain=["prop"])],
        )

        if self.query.type == "group":
            return ast.And(
                exprs=[
                    field_filter,
                    ast.CompareOperation(
                        left=ast.Field(chain=["index"]),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value=self.query.group_type_index),
                    ),
                ]
            )

        return field_filter

    def _get_subquery(self) -> ast.SelectQuery:
        query = ast.SelectQuery(
            select=[ast.Alias(expr=ast.Field(chain=["properties", self.query.property]), alias="prop")],
            distinct=True,
            select_from=ast.JoinExpr(table=ast.Field(chain=[self._origin])),
            where=self._subquery_filter(),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["created_at"]), order="DESC")],
        )
        return query
