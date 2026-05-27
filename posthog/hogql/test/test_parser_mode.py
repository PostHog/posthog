from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import ParserMode

from posthog.hogql import (
    ast,
    parser as parser_module,
)
from posthog.hogql.errors import SyntaxError as HogQLSyntaxError
from posthog.hogql.parser import HogQLParserShadowMismatch, _resolve_parser_mode, parse_select


class TestParserMode(BaseTest):
    @parameterized.expand(
        [
            # Absent modifier defaults to cpp primary + rust-py shadow; divergence raises in TEST, reports in prod.
            (None, ("cpp-json", "rust-py")),
            (ParserMode.CPP_ONLY, ("cpp-json", None)),
            (ParserMode.RUST_ONLY, ("rust-json", None)),
            (ParserMode.CPP_WITH_RUST_SHADOW, ("cpp-json", "rust-json")),
            (ParserMode.CPP_WITH_RUST_PY_SHADOW, ("cpp-json", "rust-py")),
            (ParserMode.RUST_WITH_CPP_SHADOW, ("rust-json", "cpp-json")),
            (ParserMode.RUST_PY_ONLY, ("rust-py", None)),
            (ParserMode.RUST_PY_WITH_CPP_SHADOW, ("rust-py", "cpp-json")),
        ]
    )
    def test_resolve_parser_mode(self, mode, expected):
        self.assertEqual(_resolve_parser_mode(mode, "cpp-json"), expected)

    def test_resolve_parser_mode_honours_explicit_backend_when_absent(self):
        # With no modifier, an explicit backend= override still wins and disables the auto-shadow, even in TEST.
        self.assertEqual(_resolve_parser_mode(None, "rust-json"), ("rust-json", None))

    def test_resolve_parser_mode_shadows_in_prod_too(self):
        # The default shadow isn't gated on settings.TEST: an absent modifier resolves to cpp + rust-py shadow in prod.
        with patch("posthog.hogql.parser.settings") as mock_settings:
            mock_settings.TEST = False
            self.assertEqual(_resolve_parser_mode(None, "cpp-json"), ("cpp-json", "rust-py"))

    def test_resolve_parser_mode_drops_shadow_when_rust_unavailable(self):
        # If the rust wheel failed to import, the default drops the shadow and runs cpp-only, never throwing.
        with patch("posthog.hogql.parser._RUST_PARSER_AVAILABLE", False):
            self.assertEqual(_resolve_parser_mode(None, "cpp-json"), ("cpp-json", None))

    def test_shadow_silent_when_backends_agree(self):
        # A *_shadow mode parses with the shadow backend on every sampled query; matching ASTs report nothing.
        with patch("posthog.hogql.parser._SHADOW_SAMPLE_RATE", 1.0):
            with patch("posthog.hogql.parser.capture_exception") as captured:
                node = parse_select("select 1 from events", parser_mode=ParserMode.CPP_WITH_RUST_SHADOW)
        self.assertIsInstance(node, ast.SelectQuery)
        captured.assert_not_called()

    def test_shadow_raises_mismatch_in_test_mode(self):
        # In TEST the shadow comparison raises on divergence; only the shadow diverges, the primary parses for real.
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
        # In prod the shadow comparison captures the mismatch and returns the primary result, never raising.
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
        # rust_only routes the parse entirely through the Rust backend.
        node = parse_select("select a, b from events where a > 1", parser_mode=ParserMode.RUST_ONLY)
        self.assertIsInstance(node, ast.SelectQuery)

    def test_shadow_raises_parser_class_throw_in_test_mode(self):
        # A BaseHogQLError from the shadow means it rejected primary-accepted input (a regression); raise in TEST.
        real_invoke = parser_module._invoke_parser

        def shadow_throws_parser_class(backend, rule, statement, start):
            if backend == "rust-json":
                raise HogQLSyntaxError("simulated rust-json regression")
            return real_invoke(backend, rule, statement, start)

        with patch("posthog.hogql.parser._invoke_parser", side_effect=shadow_throws_parser_class):
            with patch("posthog.hogql.parser.capture_exception"):
                with self.assertRaises(HogQLSyntaxError):
                    parse_select("select 1 from events", parser_mode=ParserMode.CPP_WITH_RUST_SHADOW)

    def test_shadow_rejected_records_and_captures_sql_in_prod(self):
        # Prod: a shadow rejecting primary-accepted input counts as shadow_rejected and captures the SQL; no raise.
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

    def test_shadow_swallows_packaging_class_throw_in_test_mode(self):
        # A non-BaseHogQLError (broken wheel, PyO3 panic) is a packaging issue: counted and captured, never raised.
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

    def test_shadow_counts_agreement(self):
        # Every shadowed parse counts; a match lands under result="agree" tagged with both wheel versions.
        with patch("posthog.hogql.parser._SHADOW_COMPARISONS") as counter:
            with patch("posthog.hogql.parser.capture_exception") as captured:
                parse_select("select 1 from events", parser_mode=ParserMode.CPP_WITH_RUST_PY_SHADOW)
        self.assertEqual([c.kwargs.get("result") for c in counter.labels.call_args_list], ["agree"])
        agree_call = counter.labels.call_args_list[0]
        self.assertEqual(agree_call.kwargs["primary_version"], parser_module._BACKEND_VERSION["cpp-json"])
        self.assertEqual(agree_call.kwargs["shadow_version"], parser_module._BACKEND_VERSION["rust-py"])
        captured.assert_not_called()

    def test_shadow_divergence_counts_disagree_and_captures_sql(self):
        # A divergence counts as result="disagree" and captures the query to error tracking; prod, so no raise.
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

    def test_parser_version_falls_back_to_unknown_for_missing_dist(self):
        # A backend whose wheel has no distribution metadata reports "unknown" instead of raising.
        self.assertEqual(parser_module._parser_version("definitely-not-a-real-distribution"), "unknown")

    def test_backend_version_map_covers_every_backend(self):
        # Every backend resolves to a version label, so the histogram and counter never emit an unlabelled series.
        self.assertEqual(set(parser_module._BACKEND_VERSION), set(parser_module.RULE_TO_PARSE_FUNCTION))
