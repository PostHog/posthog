from typing import Optional

from posthog.schema import (
    ActorsPropertyTaxonomyQuery,
    ActorsPropertyTaxonomyQueryResponse,
    CachedActorsPropertyTaxonomyQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.ai.utils import TaxonomyCacheMixin
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner


class ActorsPropertyTaxonomyQueryRunner(TaxonomyCacheMixin, AnalyticsQueryRunner[ActorsPropertyTaxonomyQueryResponse]):
    MAX_PROPERTY_LIMIT = 200

    query: ActorsPropertyTaxonomyQuery
    cached_response: CachedActorsPropertyTaxonomyQueryResponse
    settings: HogQLGlobalSettings | None

    def __init__(self, *args, settings: HogQLGlobalSettings | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings = settings

    def _calculate(self):
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team)

        response = execute_hogql_query(
            query_type="ActorsPropertyTaxonomyQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        # Map results by prop_index (1-based from arrayEnumerate) back to input order
        num_props = len(self.query.properties)
        results_by_index: list[dict] = [{"sample_values": [], "sample_count": 0} for _ in range(num_props)]

        for sample_values, sample_count, prop_index in response.results or []:
            idx = int(prop_index) - 1
            if 0 <= idx < num_props:
                results_by_index[idx] = {
                    "sample_values": sample_values,
                    "sample_count": sample_count,
                }

        return ActorsPropertyTaxonomyQueryResponse(
            results=results_by_index,
            timings=response.timings,
            hogql=hogql,
            modifiers=self.modifiers,
        )

    def to_query(self) -> ast.SelectQuery:
        query = ast.SelectQuery(
            select=[
                ast.Call(
                    name="groupArray",
                    args=[ast.Field(chain=["prop"])],
                    params=[ast.Constant(value=self.query.maxPropertyValues or 5)],
                ),
                ast.Call(name="count", args=[]),
                ast.Field(chain=["prop_index"]),
            ],
            select_from=ast.JoinExpr(table=self._get_subquery()),
            group_by=[ast.Field(chain=["prop_index"])],
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["prop_index"]), order="ASC")],
        )

        return query

    @property
    def _actor_type(self) -> str:
        if self.query.groupTypeIndex is not None:
            return "group"
        return "person"

    @property
    def _origin(self) -> str:
        if self._actor_type == "person":
            return "persons"
        return "groups"

    def _subquery_filter(self, *, field_name: str = "prop") -> Optional[ast.Expr]:
        field_filter = ast.Call(
            name="isNotNull",
            args=[ast.Field(chain=[field_name])],
        )

        if self._actor_type == "group":
            return ast.And(
                exprs=[
                    field_filter,
                    ast.CompareOperation(
                        left=ast.Field(chain=["index"]),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value=self.query.groupTypeIndex),
                    ),
                ]
            )

        return field_filter

    def _get_subquery(self) -> ast.SelectQuery:
        inner_props_array = ast.Array(
            exprs=[
                ast.Call(name="toString", args=[ast.Field(chain=["properties", p])])
                for p in self.query.properties[: self.MAX_PROPERTY_LIMIT]
            ]
        )

        return ast.SelectQuery(
            select=[
                ast.Field(chain=["prop_index"]),
                ast.Alias(alias="prop", expr=ast.Call(name="toString", args=[ast.Field(chain=["prop_value"])])),
            ],
            distinct=True,
            select_from=ast.JoinExpr(table=ast.Field(chain=[self._origin])),
            where=self._subquery_filter(field_name="prop_value"),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["created_at"]), order="DESC")],
            array_join_op="ARRAY JOIN",
            array_join_list=[
                ast.Alias(alias="prop_index", expr=ast.Call(name="arrayEnumerate", args=[inner_props_array])),
                ast.Alias(alias="prop_value", expr=inner_props_array),
            ],
        )
