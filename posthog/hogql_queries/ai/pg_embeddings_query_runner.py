from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.ai.utils import TaxonomyCacheMixin
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    CachedPgEmbeddingsQueryResponse,
    PgEmbeddingsQuery,
    PgEmbeddingsQueryResponse,
    PgEmbeddingsResponseItem,
)


class PgEmbeddingsQueryRunner(TaxonomyCacheMixin, QueryRunner):
    query: PgEmbeddingsQuery
    response: PgEmbeddingsQueryResponse
    cached_response: CachedPgEmbeddingsQueryResponse

    def calculate(self):
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team)

        response = execute_hogql_query(
            query_type="PgEmbeddingsQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        results: list[PgEmbeddingsResponseItem] = []
        for id, distance in response.results:
            results.append(PgEmbeddingsResponseItem(id=id, distance=distance))

        return PgEmbeddingsQueryResponse(
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
                cosineDistance(vector, {embedding}) as distance
            FROM
                pg_embeddings
            WHERE
                domain = 'action'
            ORDER BY
                distance ASC
            LIMIT 20
            """,
            placeholders={
                "embedding": ast.Constant(value=self.query.embedding),
            },
        )
