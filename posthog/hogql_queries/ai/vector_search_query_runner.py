from posthog.schema import (
    CachedVectorSearchQueryResponse,
    VectorSearchQuery,
    VectorSearchQueryResponse,
    VectorSearchResponseItem,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.ai.utils import TaxonomyCacheMixin
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

LATEST_ACTIONS_EMBEDDING_VERSION: int = 2
"""Bump the version when the embedding behavior changes for actions."""


class VectorSearchQueryRunner(TaxonomyCacheMixin, AnalyticsQueryRunner[VectorSearchQueryResponse]):
    query: VectorSearchQuery
    cached_response: CachedVectorSearchQueryResponse

    def _calculate(self):
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team)

        response = execute_hogql_query(
            query_type="VectorSearchQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        results: list[VectorSearchResponseItem] = []
        for id, distance in response.results:
            results.append(VectorSearchResponseItem(id=id, distance=distance))

        return VectorSearchQueryResponse(
            results=results,
            timings=response.timings,
            hogql=hogql,
            modifiers=self.modifiers,
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
            SELECT
                id,
                cosineDistance(argMax(vector, timestamp), {embedding}) as distance
            FROM
                pg_embeddings
            WHERE
                {where_clause}
            GROUP BY
                id
            ORDER BY
                distance ASC
            LIMIT 20
            """,
            placeholders={
                "embedding": ast.Constant(value=self.query.embedding),
                "where_clause": self._get_where_clause(),
            },
        )

    def _get_where_clause(self) -> ast.Expr:
        base_filter = parse_expr("domain = 'action' and is_deleted = 0")
        if self.query.embeddingVersion is not None:
            return ast.And(
                exprs=[
                    base_filter,
                    parse_expr(
                        "JSONExtractUInt(properties, 'embedding_version') = {version}",
                        {"version": ast.Constant(value=self.query.embeddingVersion)},
                    ),
                ]
            )
        return base_filter
