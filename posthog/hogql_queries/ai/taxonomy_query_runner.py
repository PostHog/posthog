from posthog.hogql import ast
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import CachedTaxonomyQueryResponse, TaxonomyQuery, TaxonomyQueryResponse


class TaxonomyQueryRunner(QueryRunner):
    query: TaxonomyQuery
    response: TaxonomyQueryResponse
    cached_response: CachedTaxonomyQueryResponse

    def calculate(self):
        pass

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        pass
