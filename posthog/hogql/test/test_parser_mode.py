from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import ParserMode

from posthog.hogql import (
    ast,
    parser as parser_module,
)
from posthog.hogql.errors import SyntaxError as HogQLSyntaxError
from posthog.hogql.parser import HogQLParserShadowMismatch, _resolve_parser_mode, parse_expr, parse_select


class TestParserMode(BaseTest):
    @parameterized.expand(
        [
            # No mode + no explicit backend under TEST → rust-py only, cpp never runs.
            (None, None, ("rust-py", None)),
            # No mode + explicit backend → honour the explicit backend, no shadow.
            (None, "cpp-json", ("cpp-json", None)),
            (None, "rust-json", ("rust-json", None)),
            (None, "rust-py", ("rust-py", None)),
            (ParserMode.CPP_ONLY, None, ("cpp-json", None)),
            (ParserMode.RUST_ONLY, None, ("rust-json", None)),
            (ParserMode.CPP_WITH_RUST_SHADOW, None, ("cpp-json", "rust-json")),
            (ParserMode.CPP_WITH_RUST_PY_SHADOW, None, ("cpp-json", "rust-py")),
            (ParserMode.RUST_WITH_CPP_SHADOW, None, ("rust-json", "cpp-json")),
            (ParserMode.RUST_PY_ONLY, None, ("rust-py", None)),
            (ParserMode.RUST_PY_WITH_CPP_SHADOW, None, ("rust-py", "cpp-json")),
        ]
    )
    def test_resolve_parser_mode(self, mode, backend, expected):
        self.assertEqual(_resolve_parser_mode(mode, backend), expected)

    def test_resolve_parser_mode_default_shadows_in_prod(self):
        with patch("posthog.hogql.parser.settings") as mock_settings:
            mock_settings.TEST = False
            self.assertEqual(_resolve_parser_mode(None, None), ("rust-py", "cpp-json"))

    def test_resolve_parser_mode_drops_shadow_when_rust_unavailable(self):
        with patch("posthog.hogql.parser._RUST_PARSER_AVAILABLE", False):
            self.assertEqual(_resolve_parser_mode(None, None), ("cpp-json", None))

    def test_resolve_parser_mode_rejects_both_mode_and_backend(self):
        with self.assertRaises(ValueError):
            _resolve_parser_mode(ParserMode.RUST_PY_ONLY, "cpp-json")

    def test_shadow_silent_when_backends_agree(self):
        with patch("posthog.hogql.parser._SHADOW_SAMPLE_RATE", 1.0):
            with patch("posthog.hogql.parser.capture_exception") as captured:
                node = parse_select("select 1 from events", parser_mode=ParserMode.CPP_WITH_RUST_SHADOW)
        self.assertIsInstance(node, ast.SelectQuery)
        captured.assert_not_called()

    def test_shadow_raises_mismatch_in_test_mode(self):
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

    def test_shadow_captures_mismatch_without_raising_in_prod(self):
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
        node = parse_select("select a, b from events where a > 1", parser_mode=ParserMode.RUST_ONLY)
        self.assertIsInstance(node, ast.SelectQuery)

    def test_shadow_raises_when_shadow_rejects_primary_accepted_input_in_test_mode(self):
        real_invoke = parser_module._invoke_parser

        def shadow_throws_parser_class(backend, rule, statement, start):
            if backend == "rust-json":
                raise HogQLSyntaxError("simulated rust-json regression")
            return real_invoke(backend, rule, statement, start)

        with patch("posthog.hogql.parser._invoke_parser", side_effect=shadow_throws_parser_class):
            with patch("posthog.hogql.parser.capture_exception"):
                with self.assertRaises(HogQLSyntaxError):
                    parse_select("select 1 from events", parser_mode=ParserMode.CPP_WITH_RUST_SHADOW)

    def test_shadow_rejection_counts_and_captures_sql_without_raising_in_prod(self):
        real_invoke = parser_module._invoke_parser

        def shadow_throws_parser_class(backend, rule, statement, start):
            if backend == "rust-py":
                raise HogQLSyntaxError("simulated rust-py rejection")
            return real_invoke(backend, rule, statement, start)

        with patch("posthog.hogql.parser.settings") as mock_settings:
            mock_settings.TEST = False
            with patch("posthog.hogql.parser._SHADOW_SAMPLE_RATE", 1.0):
                with patch("posthog.hogql.parser._invoke_parser", side_effect=shadow_throws_parser_class):
                    with patch("posthog.hogql.parser._SHADOW_COMPARISONS") as counter:
                        with patch("posthog.hogql.parser.capture_exception") as captured:
                            node = parse_select(
                                "select shadow_rejected_probe from events",
                                parser_mode=ParserMode.CPP_WITH_RUST_PY_SHADOW,
                            )
        self.assertIsInstance(node, ast.SelectQuery)
        results = [c.kwargs.get("result") for c in counter.labels.call_args_list]
        self.assertIn("shadow_rejected", results)
        captured.assert_called_once()
        props = captured.call_args.kwargs["additional_properties"]
        self.assertIn("shadow_rejected_probe", props["hogql_parser_statement"])
        self.assertEqual(props["hogql_parser_shadow_version"], parser_module._BACKEND_VERSION["rust-py"])

    def test_shadow_swallows_non_parser_packaging_error_even_in_test_mode(self):
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

    def test_shadow_agreement_counts_as_agree_with_parser_version_labels(self):
        with patch("posthog.hogql.parser._SHADOW_COMPARISONS") as counter:
            with patch("posthog.hogql.parser.capture_exception") as captured:
                parse_select("select 1 from events", parser_mode=ParserMode.CPP_WITH_RUST_PY_SHADOW)
        self.assertEqual([c.kwargs.get("result") for c in counter.labels.call_args_list], ["agree"])
        agree_call = counter.labels.call_args_list[0]
        self.assertEqual(agree_call.kwargs["primary_version"], parser_module._BACKEND_VERSION["cpp-json"])
        self.assertEqual(agree_call.kwargs["shadow_version"], parser_module._BACKEND_VERSION["rust-py"])
        captured.assert_not_called()

    def test_shadow_divergence_counts_as_disagree_and_captures_sql_in_prod(self):
        decoy = ast.SelectQuery(select=[ast.Constant(value=999)])
        real_invoke = parser_module._invoke_parser

        def only_shadow_diverges(backend, rule, statement, start):
            if backend == "rust-py":
                return decoy
            return real_invoke(backend, rule, statement, start)

        with patch("posthog.hogql.parser.settings") as mock_settings:
            mock_settings.TEST = False
            with patch("posthog.hogql.parser._SHADOW_SAMPLE_RATE", 1.0):
                with patch("posthog.hogql.parser._invoke_parser", side_effect=only_shadow_diverges):
                    with patch("posthog.hogql.parser._SHADOW_COMPARISONS") as counter:
                        with patch("posthog.hogql.parser.capture_exception") as captured:
                            parse_select(
                                "select sql_attach_probe from events",
                                parser_mode=ParserMode.CPP_WITH_RUST_PY_SHADOW,
                            )
        results = [c.kwargs.get("result") for c in counter.labels.call_args_list]
        self.assertIn("disagree", results)
        captured.assert_called_once()
        self.assertIsInstance(captured.call_args.args[0], HogQLParserShadowMismatch)
        props = captured.call_args.kwargs["additional_properties"]
        self.assertEqual(props["hogql_parser_rule"], "select")
        self.assertIn("sql_attach_probe", props["hogql_parser_statement"])
        self.assertEqual(props["hogql_parser_primary_version"], parser_module._BACKEND_VERSION["cpp-json"])
        self.assertEqual(props["hogql_parser_shadow_version"], parser_module._BACKEND_VERSION["rust-py"])

    def test_shadow_treats_nan_constant_as_agreement_not_divergence(self):
        with patch("posthog.hogql.parser._SHADOW_COMPARISONS") as counter:
            node = parse_expr("nan", parser_mode=ParserMode.CPP_WITH_RUST_PY_SHADOW)
        self.assertIsInstance(node, ast.Constant)
        self.assertEqual([c.kwargs.get("result") for c in counter.labels.call_args_list], ["agree"])

    def test_parser_version_falls_back_to_unknown_for_missing_dist(self):
        self.assertEqual(parser_module._parser_version("definitely-not-a-real-distribution"), "unknown")

    def test_backend_version_map_covers_every_parse_backend(self):
        self.assertEqual(set(parser_module._BACKEND_VERSION), set(parser_module.RULE_TO_PARSE_FUNCTION))
