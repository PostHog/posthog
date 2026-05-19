from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import ParserMode

from posthog.hogql import ast
from posthog.hogql.parser import HogQLParserShadowMismatch, _resolve_parser_mode, parse_select


class TestParserMode(BaseTest):
    @parameterized.expand(
        [
            (None, ("cpp-json", None)),
            (ParserMode.CPP_ONLY, ("cpp-json", None)),
            (ParserMode.RUST_ONLY, ("rust-json", None)),
            (ParserMode.CPP_WITH_RUST_SHADOW, ("cpp-json", "rust-json")),
            (ParserMode.RUST_WITH_CPP_SHADOW, ("rust-json", "cpp-json")),
        ]
    )
    def test_resolve_parser_mode(self, mode, expected):
        # An absent modifier resolves to the explicit `backend` arg with no
        # shadow; every named mode maps to its (primary, shadow) pair.
        self.assertEqual(_resolve_parser_mode(mode, "cpp-json"), expected)

    def test_resolve_parser_mode_honours_explicit_backend_when_absent(self):
        # With no modifier the `backend=` override still wins — this is the
        # path the test/diagnostic harness relies on.
        self.assertEqual(_resolve_parser_mode(None, "rust-json"), ("rust-json", None))

    def test_shadow_silent_when_backends_agree(self):
        # A `*_shadow` mode parses with the shadow backend on every sampled
        # query; when the ASTs match, nothing is reported.
        with patch("posthog.hogql.parser._SHADOW_SAMPLE_RATE", 1.0):
            with patch("posthog.hogql.parser.capture_exception") as captured:
                node = parse_select("select 1 from events", parser_mode=ParserMode.CPP_WITH_RUST_SHADOW)
        self.assertIsInstance(node, ast.SelectQuery)
        captured.assert_not_called()

    def test_shadow_reports_mismatch_without_failing(self):
        # When the shadow backend yields a different AST, the divergence is
        # sent to error tracking — but the primary result is still returned
        # and the request does not fail. Only the shadow backend is forced
        # to diverge; the primary still parses for real.
        from posthog.hogql import parser as parser_module

        decoy = ast.SelectQuery(select=[ast.Constant(value=999)])
        real_invoke = parser_module._invoke_parser

        def only_shadow_diverges(backend, rule, statement, start):
            if backend == "rust-json":
                return decoy
            return real_invoke(backend, rule, statement, start)

        with patch("posthog.hogql.parser._SHADOW_SAMPLE_RATE", 1.0):
            with patch("posthog.hogql.parser._invoke_parser", side_effect=only_shadow_diverges):
                with patch("posthog.hogql.parser.capture_exception") as captured:
                    node = parse_select(
                        "select shadow_mismatch_probe from events", parser_mode=ParserMode.CPP_WITH_RUST_SHADOW
                    )
        self.assertIsInstance(node, ast.SelectQuery)
        captured.assert_called_once()
        self.assertIsInstance(captured.call_args.args[0], HogQLParserShadowMismatch)

    def test_rust_only_parses_through_the_rust_backend(self):
        # `rust_only` routes the parse entirely through the Rust backend.
        node = parse_select("select a, b from events where a > 1", parser_mode=ParserMode.RUST_ONLY)
        self.assertIsInstance(node, ast.SelectQuery)
