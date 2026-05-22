from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import ParserMode

from posthog.hogql import ast
from posthog.hogql.parser import HogQLParserShadowMismatch, _resolve_parser_mode, parse_select


class TestParserMode(BaseTest):
    @parameterized.expand(
        [
            # An absent modifier in TEST defaults to CPP_WITH_RUST_SHADOW so
            # every test-suite parse exercises both backends and raises on
            # divergence (see `_run_shadow_comparison`).
            (None, ("cpp-json", "rust-json")),
            (ParserMode.CPP_ONLY, ("cpp-json", None)),
            (ParserMode.RUST_ONLY, ("rust-json", None)),
            (ParserMode.CPP_WITH_RUST_SHADOW, ("cpp-json", "rust-json")),
            (ParserMode.RUST_WITH_CPP_SHADOW, ("rust-json", "cpp-json")),
            (ParserMode.RUST_PY_ONLY, ("rust-py", None)),
            (ParserMode.RUST_PY_WITH_CPP_SHADOW, ("rust-py", "cpp-json")),
        ]
    )
    def test_resolve_parser_mode(self, mode, expected):
        self.assertEqual(_resolve_parser_mode(mode, "cpp-json"), expected)

    def test_resolve_parser_mode_honours_explicit_backend_when_absent(self):
        # With no modifier the `backend=` override still wins — this is the
        # path the test/diagnostic harness relies on. Even in TEST, an
        # explicit non-default backend disables the auto-shadow.
        self.assertEqual(_resolve_parser_mode(None, "rust-json"), ("rust-json", None))

    def test_resolve_parser_mode_prod_absent_modifier_no_shadow(self):
        # The TEST-only auto-shadow is gated on `settings.TEST`; with that
        # flag off (i.e. production) an absent modifier means "no shadow".
        with patch("posthog.hogql.parser.settings") as mock_settings:
            mock_settings.TEST = False
            self.assertEqual(_resolve_parser_mode(None, "cpp-json"), ("cpp-json", None))

    def test_shadow_silent_when_backends_agree(self):
        # A `*_shadow` mode parses with the shadow backend on every sampled
        # query; when the ASTs match, nothing is reported.
        with patch("posthog.hogql.parser._SHADOW_SAMPLE_RATE", 1.0):
            with patch("posthog.hogql.parser.capture_exception") as captured:
                node = parse_select("select 1 from events", parser_mode=ParserMode.CPP_WITH_RUST_SHADOW)
        self.assertIsInstance(node, ast.SelectQuery)
        captured.assert_not_called()

    def test_shadow_raises_mismatch_in_test_mode(self):
        # In TEST the shadow comparison raises on divergence, so a test
        # whose parser produces a mismatched AST fails loudly. Only the
        # shadow backend is forced to diverge; the primary still parses
        # for real.
        from posthog.hogql import parser as parser_module

        decoy = ast.SelectQuery(select=[ast.Constant(value=999)])
        real_invoke = parser_module._invoke_parser

        def only_shadow_diverges(backend, rule, statement, start):
            if backend == "rust-json":
                return decoy
            return real_invoke(backend, rule, statement, start)

        with patch("posthog.hogql.parser._invoke_parser", side_effect=only_shadow_diverges):
            with self.assertRaises(HogQLParserShadowMismatch):
                parse_select(
                    "select shadow_mismatch_probe from events",
                    parser_mode=ParserMode.CPP_WITH_RUST_SHADOW,
                )

    def test_shadow_reports_mismatch_without_failing_in_prod(self):
        # In production (`settings.TEST = False`) the shadow comparison
        # captures the mismatch to error tracking and returns the primary
        # result — never raises into a request.
        from posthog.hogql import parser as parser_module

        decoy = ast.SelectQuery(select=[ast.Constant(value=999)])
        real_invoke = parser_module._invoke_parser

        def only_shadow_diverges(backend, rule, statement, start):
            if backend == "rust-json":
                return decoy
            return real_invoke(backend, rule, statement, start)

        with patch("posthog.hogql.parser._SHADOW_SAMPLE_RATE", 1.0):
            with patch("posthog.hogql.parser.settings") as mock_settings:
                mock_settings.TEST = False
                with patch("posthog.hogql.parser._invoke_parser", side_effect=only_shadow_diverges):
                    with patch("posthog.hogql.parser.capture_exception") as captured:
                        node = parse_select(
                            "select shadow_mismatch_probe from events",
                            parser_mode=ParserMode.CPP_WITH_RUST_SHADOW,
                        )
        self.assertIsInstance(node, ast.SelectQuery)
        captured.assert_called_once()
        self.assertIsInstance(captured.call_args.args[0], HogQLParserShadowMismatch)

    def test_rust_only_parses_through_the_rust_backend(self):
        # `rust_only` routes the parse entirely through the Rust backend.
        node = parse_select("select a, b from events where a > 1", parser_mode=ParserMode.RUST_ONLY)
        self.assertIsInstance(node, ast.SelectQuery)

    def test_shadow_raises_parser_class_throw_in_test_mode(self):
        # A `BaseHogQLError` from the shadow backend means it rejected what
        # the primary accepted — a real parser regression. Propagate in TEST
        # so a unit-suite parse hitting the regression fails loudly.
        from posthog.hogql import parser as parser_module
        from posthog.hogql.errors import SyntaxError as HogQLSyntaxError

        real_invoke = parser_module._invoke_parser

        def shadow_throws_parser_class(backend, rule, statement, start):
            if backend == "rust-json":
                raise HogQLSyntaxError("simulated rust-json regression")
            return real_invoke(backend, rule, statement, start)

        with patch("posthog.hogql.parser._invoke_parser", side_effect=shadow_throws_parser_class):
            with patch("posthog.hogql.parser.capture_exception"):
                with self.assertRaises(HogQLSyntaxError):
                    parse_select("select 1 from events", parser_mode=ParserMode.CPP_WITH_RUST_SHADOW)

    def test_shadow_swallows_packaging_class_throw_in_test_mode(self):
        # A non-BaseHogQLError exception (ImportError, RuntimeError from a
        # broken wheel, PyO3 panic) is treated as a packaging issue — never
        # propagates, even in TEST. Captures + counts.
        from posthog.hogql import parser as parser_module

        real_invoke = parser_module._invoke_parser

        def shadow_throws_packaging(backend, rule, statement, start):
            if backend == "rust-json":
                raise ImportError("simulated wheel failure")
            return real_invoke(backend, rule, statement, start)

        with patch("posthog.hogql.parser._invoke_parser", side_effect=shadow_throws_packaging):
            with patch("posthog.hogql.parser.capture_exception") as captured:
                node = parse_select("select 1 from events", parser_mode=ParserMode.CPP_WITH_RUST_SHADOW)
        self.assertIsInstance(node, ast.SelectQuery)
        captured.assert_called_once()
        self.assertIsInstance(captured.call_args.args[0], ImportError)
