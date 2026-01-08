from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing


class TestDocumentEmbeddingsOrderByPushdown(BaseTest):
    def _get_inner_query(self, query_str: str) -> ast.SelectQuery:
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        query = parse_select(query_str)
        prepared = prepare_ast_for_printing(query, context, dialect="clickhouse")
        assert prepared is not None
        assert isinstance(prepared, ast.SelectQuery)
        assert prepared.select_from is not None
        inner_query = prepared.select_from.table
        assert isinstance(inner_query, ast.SelectQuery)
        return inner_query

    @parameterized.expand(
        [
            ("cosineDistance",),
            ("L2Distance",),
        ]
    )
    def test_order_by_and_limit_pushed_down_for_vector_distance(self, distance_func: str):
        query = f"""
            SELECT *
            FROM document_embeddings
            WHERE model_name = 'text-embedding-3-large-3072'
            ORDER BY {distance_func}(embedding, [1.0, 2.0, 3.0]) ASC
            LIMIT 10
        """
        inner_query = self._get_inner_query(query)

        assert inner_query.order_by is not None, "ORDER BY should be pushed down to inner query"
        assert len(inner_query.order_by) == 1
        assert inner_query.limit is not None, "LIMIT should be pushed down to inner query"
        assert isinstance(inner_query.limit, ast.Constant)
        assert inner_query.limit.value == 10

    def test_order_by_alias_pushed_down(self):
        query = """
            SELECT cosineDistance(embedding, [1.0, 2.0, 3.0]) AS dist
            FROM document_embeddings
            WHERE model_name = 'text-embedding-3-large-3072'
            ORDER BY dist ASC
            LIMIT 10
        """
        inner_query = self._get_inner_query(query)

        assert inner_query.order_by is not None, "ORDER BY should be pushed down when referencing distance alias"
        assert inner_query.limit is not None

    def test_no_pushdown_without_limit(self):
        query = """
            SELECT *
            FROM document_embeddings
            WHERE model_name = 'text-embedding-3-large-3072'
            ORDER BY cosineDistance(embedding, [1.0, 2.0, 3.0]) ASC
        """
        inner_query = self._get_inner_query(query)

        assert inner_query.order_by is None, "ORDER BY should not be pushed without LIMIT"
        assert inner_query.limit is None

    def test_no_pushdown_for_non_distance_order(self):
        query = """
            SELECT *
            FROM document_embeddings
            WHERE model_name = 'text-embedding-3-large-3072'
            ORDER BY timestamp DESC
            LIMIT 10
        """
        inner_query = self._get_inner_query(query)

        assert inner_query.order_by is None, "ORDER BY should not be pushed for non-distance functions"
        assert inner_query.limit is None

    def test_multiple_order_by_columns_pushed_down(self):
        query = """
            SELECT *
            FROM document_embeddings
            WHERE model_name = 'text-embedding-3-large-3072'
            ORDER BY cosineDistance(embedding, [1.0, 2.0, 3.0]) ASC, timestamp DESC
            LIMIT 10
        """
        inner_query = self._get_inner_query(query)

        assert inner_query.order_by is not None, "ORDER BY should be pushed down for multiple columns"
        assert len(inner_query.order_by) == 2
        assert inner_query.limit is not None

    def test_offset_not_pushed_down(self):
        query = """
            SELECT *
            FROM document_embeddings
            WHERE model_name = 'text-embedding-3-large-3072'
            ORDER BY cosineDistance(embedding, [1.0, 2.0, 3.0]) ASC
            LIMIT 10 OFFSET 5
        """
        inner_query = self._get_inner_query(query)

        assert inner_query.order_by is not None
        assert inner_query.limit is not None
        assert inner_query.offset is None, "OFFSET should not be pushed down to inner query"
