from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.functions.embed_text import resolve_embed_text
from posthog.hogql.parser import parse_expr
from posthog.hogql.printer import print_prepared_ast

from posthog.models.team.team import Team

from products.error_tracking.backend.indexed_embedding import EMBEDDING_TABLES


class TestEmbedText(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing", "embedText('example text')"),
            ("empty", "embedText('example text', '')"),
            ("unknown", "embedText('example text', 'unknown-model')"),
        ]
    )
    def test_invalid_model_is_a_query_error(self, _name: str, expression: str) -> None:
        context = HogQLContext(team_id=1, team=Team(id=1))

        with self.assertRaises(QueryError) as raised:
            print_prepared_ast(parse_expr(expression), context=context, dialect="clickhouse")

        self.assertIn("Valid models are:", str(raised.exception))
        for table in EMBEDDING_TABLES:
            self.assertIn(table.model_name, str(raised.exception))

    @parameterized.expand(
        [
            ("missing_team", False, [ast.Constant(value="example text")], "requires a team or team ID"),
            ("no_arguments", True, [], "takes at least one argument"),
            ("too_many_arguments", True, [ast.Constant(value="x")] * 3, "takes at most two arguments"),
            ("invalid_text", True, [ast.Constant(value=1)], "first argument must be a string literal"),
            (
                "invalid_model_type",
                True,
                [ast.Constant(value="example text"), ast.Constant(value=1)],
                "second argument must be a string literal",
            ),
        ]
    )
    def test_invalid_arguments_are_query_errors(
        self, _name: str, has_team: bool, args: list[ast.Expr], message: str
    ) -> None:
        node = ast.Call(name="embedText", args=args, start=0, end=20)

        with self.assertRaisesRegex(QueryError, message) as raised:
            resolve_embed_text(Team(id=1) if has_team else None, node)

        self.assertEqual((raised.exception.start, raised.exception.end), (node.start, node.end))

    @patch("posthog.api.embedding_worker.internal_requests.post")
    def test_valid_model_returns_embedding(self, post: MagicMock) -> None:
        model = EMBEDDING_TABLES[0].model_name
        post.return_value.json.return_value = {
            "embedding": [0.1, 0.2, 0.3],
            "tokens_used": 2,
            "did_truncate": False,
        }

        result = resolve_embed_text(
            Team(id=1),
            ast.Call(name="embedText", args=[ast.Constant(value="example text"), ast.Constant(value=model)]),
        )

        self.assertEqual(result.value, [0.1, 0.2, 0.3])
        self.assertEqual(
            post.call_args.kwargs["json"],
            {"team_id": 1, "content": "example text", "no_truncate": True, "model": model},
        )
