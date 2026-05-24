from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import ParserMode

from posthog.hogql import ast
from posthog.hogql.parser import HogQLParserShadowMismatch, _resolve_parser_mode, parse_select


class TestParserMode(BaseTest):
    @parameterized.expand(
        [
            # An absent modifier in TEST stays CPP_WITH_RUST_SHADOW so the suite
            # parses on the cpp primary its AST snapshots were recorded against,
            # with rust-json as a 100% shadow. The prod default (rust-py primary)
            # is asserted separately below.
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
        # With no modifier an explicit non-default `backend=` override still
        # wins (the path the test/diagnostic harness relies on) and gets no
        # shadow.
        self.assertEqual(_resolve_parser_mode(None, "rust-json"), ("rust-json", None))

    def test_resolve_parser_mode_prod_absent_modifier_defaults_to_rust_py_shadow(self):
        # The default applies in production too (not just TEST): an absent
        # modifier means rust-py primary with a cpp-json shadow.
        with patch("posthog.hogql.parser.settings") as mock_settings:
            mock_settings.TEST = False
            self.assertEqual(_resolve_parser_mode(None, "cpp-json"), ("rust-py", "cpp-json"))

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

    def test_shadow_emits_analytics_event_with_timings_on_match_in_prod(self):
        # In production every sampled shadow run emits an analytics event
        # carrying each backend's parse time, so the mismatch rate is a
        # fraction of a known total. A matching run carries no raw query.
        with (
            patch("posthog.hogql.parser._SHADOW_SAMPLE_RATE", 1.0),
            patch("posthog.hogql.parser.settings") as mock_settings,
            patch("posthog.hogql.parser.posthoganalytics") as mock_ph,
        ):
            mock_settings.TEST = False
            node = parse_select(
                "select a, b from events where a > 1",
                parser_mode=ParserMode.RUST_PY_WITH_CPP_SHADOW,
            )
        self.assertIsInstance(node, ast.SelectQuery)
        mock_ph.capture.assert_called_once()
        kwargs = mock_ph.capture.call_args.kwargs
        self.assertEqual(kwargs["event"], "hogql_parser_shadow_comparison")
        props = kwargs["properties"]
        self.assertTrue(props["matched"])
        self.assertEqual(props["primary_backend"], "rust-py")
        self.assertEqual(props["shadow_backend"], "cpp-json")
        self.assertIsInstance(props["primary_parse_ms"], float)
        self.assertIsInstance(props["shadow_parse_ms"], float)
        self.assertNotIn("query", props)

    def test_shadow_emits_analytics_event_with_query_on_mismatch_in_prod(self):
        # On a mismatch the event flips `matched` to False and attaches the raw
        # query so the divergent statement can be looked up. The existing
        # error-tracking capture still fires alongside it.
        from posthog.hogql import parser as parser_module

        decoy = ast.SelectQuery(select=[ast.Constant(value=999)])
        real_invoke = parser_module._invoke_parser

        def only_shadow_diverges(backend, rule, statement, start):
            if backend == "cpp-json":
                return decoy
            return real_invoke(backend, rule, statement, start)

        with (
            patch("posthog.hogql.parser._SHADOW_SAMPLE_RATE", 1.0),
            patch("posthog.hogql.parser.settings") as mock_settings,
            patch("posthog.hogql.parser._invoke_parser", side_effect=only_shadow_diverges),
            patch("posthog.hogql.parser.posthoganalytics") as mock_ph,
            patch("posthog.hogql.parser.capture_exception") as captured,
        ):
            mock_settings.TEST = False
            node = parse_select(
                "select shadow_mismatch_probe from events",
                parser_mode=ParserMode.RUST_PY_WITH_CPP_SHADOW,
            )
        self.assertIsInstance(node, ast.SelectQuery)
        mock_ph.capture.assert_called_once()
        props = mock_ph.capture.call_args.kwargs["properties"]
        self.assertFalse(props["matched"])
        self.assertEqual(props["query"], "select shadow_mismatch_probe from events")
        captured.assert_called_once()
        self.assertIsInstance(captured.call_args.args[0], HogQLParserShadowMismatch)

    def test_shadow_event_capture_failure_does_not_break_parse(self):
        # Telemetry is best-effort: a throwing capture client must never fail
        # the parse the user is waiting on.
        with (
            patch("posthog.hogql.parser._SHADOW_SAMPLE_RATE", 1.0),
            patch("posthog.hogql.parser.settings") as mock_settings,
            patch("posthog.hogql.parser.posthoganalytics") as mock_ph,
        ):
            mock_settings.TEST = False
            mock_ph.capture.side_effect = RuntimeError("capture boom")
            node = parse_select("select a from events", parser_mode=ParserMode.RUST_PY_WITH_CPP_SHADOW)
        self.assertIsInstance(node, ast.SelectQuery)

    def test_shadow_event_not_emitted_in_test_mode(self):
        # In TEST the comparison still runs (and raises on divergence), but the
        # analytics event is skipped: analytics is disabled there, and the
        # timing re-parse would otherwise tax every parse in the suite.
        with (
            patch("posthog.hogql.parser._SHADOW_SAMPLE_RATE", 1.0),
            patch("posthog.hogql.parser.posthoganalytics") as mock_ph,
        ):
            node = parse_select(
                "select a, b from events",
                parser_mode=ParserMode.RUST_PY_WITH_CPP_SHADOW,
            )
        self.assertIsInstance(node, ast.SelectQuery)
        mock_ph.capture.assert_not_called()
