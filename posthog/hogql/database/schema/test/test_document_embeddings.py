from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast, prepare_ast_for_printing

VALID_MODEL_NAME = "text-embedding-3-large-3072"
OTHER_MODEL_NAME = "text-embedding-3-small-1536"


class TestDocumentEmbeddingsOrderByPushdown(BaseTest):
    def _prepare(self, query_str: str) -> ast.SelectQuery:
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        query = parse_select(query_str)
        prepared = prepare_ast_for_printing(query, context, dialect="clickhouse")
        assert isinstance(prepared, ast.SelectQuery)
        return prepared

    def _get_inner_query(self, query_str: str) -> ast.SelectQuery:
        prepared = self._prepare(query_str)
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

    def test_only_matching_order_by_pushed_down(self):
        query = """
            SELECT *
            FROM document_embeddings
            WHERE model_name = 'text-embedding-3-large-3072'
            ORDER BY cosineDistance(embedding, [1.0, 2.0, 3.0]) ASC, timestamp DESC
            LIMIT 10
        """
        inner_query = self._get_inner_query(query)

        assert inner_query.order_by is not None
        assert len(inner_query.order_by) == 1, "Only vector distance ORDER BY should be pushed down"
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

    def test_missing_model_name_raises_query_error(self):
        # A missing filter must surface as a user-facing HogQL error, not a bare ValueError that 500s.
        with self.assertRaises(QueryError) as ctx:
            self._prepare("SELECT content FROM document_embeddings LIMIT 1")
        message = str(ctx.exception)
        assert "model_name" in message
        assert VALID_MODEL_NAME in message

    def test_invalid_model_name_raises_query_error(self):
        with self.assertRaises(QueryError) as ctx:
            self._prepare("SELECT content FROM document_embeddings WHERE model_name = 'nope' LIMIT 1")
        message = str(ctx.exception)
        assert "nope" in message
        assert VALID_MODEL_NAME in message

    def test_non_string_model_name_placeholder_raises_query_error(self):
        # A placeholder can bind a list to `model_name`. The unhashable value used to hit the dict
        # lookup and raise a TypeError that 500s; it must surface as a HogQL error instead.
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        query = parse_select(
            "SELECT content FROM document_embeddings WHERE model_name = {model_name} LIMIT 1",
            placeholders={"model_name": ast.Constant(value=["text-embedding-3-large-3072"])},
        )
        with self.assertRaises(QueryError) as ctx:
            prepare_ast_for_printing(query, context, dialect="clickhouse")
        assert VALID_MODEL_NAME in str(ctx.exception)

    def test_model_name_filter_on_outer_query_is_resolved(self):
        # The filter sits on the wrapping query, not on the select that holds the table. It must still route.
        inner = self._get_inner_query(
            f"""
            SELECT content FROM (
                SELECT content, model_name FROM document_embeddings
            ) WHERE model_name = '{VALID_MODEL_NAME}'
            """
        )
        assert isinstance(inner, ast.SelectQuery)

    def test_inner_model_name_filter_wins_over_outer(self):
        # An inner select filters on one model and the outer query names another. The select that holds
        # the table must win, so the nested scan routes to the inner model's table, not the outer's.
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        query = parse_select(
            f"""
            SELECT count() FROM document_embeddings
            WHERE model_name = '{VALID_MODEL_NAME}'
              AND document_id IN (
                SELECT document_id FROM document_embeddings WHERE model_name = '{OTHER_MODEL_NAME}'
              )
            """
        )
        sql, _ = prepare_and_print_ast(query, context, dialect="clickhouse")
        assert "text_embedding_3_small_1536" in sql, "inner scope must route to its own model's table"
        assert "text_embedding_3_large_3072" in sql, "outer scope still routes to its own model's table"
