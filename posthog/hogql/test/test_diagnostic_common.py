"""Regression tests for the shadow-mismatch fail-fast guard shared by
the PBT parser tooling (``_diagnostic_common`` helpers and the
``parser_bench`` timing harness).

The guard under test: when an oracle/candidate backend raises
``HogQLParserShadowMismatch`` it is not a single pure parser (it ran a
primary plus a shadow comparison that disagreed), so the tool aborts
the whole run rather than masking a real cpp-vs-rust divergence as a
backend crash (diagnostic) or a skipped row (bench). Every other
exception still buckets as a ``crash`` so one bad query can't abort the
run.
"""

from unittest import TestCase, mock

from parameterized import parameterized

from posthog.hogql.parser import HogQLParserShadowMismatch
from posthog.hogql.scripts import _diagnostic_common
from posthog.hogql.scripts._diagnostic_common import _safe_parse, corpus_try_parse
from posthog.hogql.scripts.parser_bench import bench

_PARSE_HELPERS = [("_safe_parse", _safe_parse), ("corpus_try_parse", corpus_try_parse)]


def _raise_shadow_mismatch(_query, *, backend):
    raise HogQLParserShadowMismatch("select parser AST mismatch: cpp-json vs rust-json")


def _raise_runtime_error(_query, *, backend):
    raise RuntimeError("half-built backend exploded")


class TestDiagnosticShadowGuard(TestCase):
    @parameterized.expand(_PARSE_HELPERS)
    def test_shadow_mismatch_aborts_the_grind(self, _name, parse_fn):
        with mock.patch.dict(_diagnostic_common._PARSER_FOR_RULE, {"select": _raise_shadow_mismatch}):
            with self.assertRaises(SystemExit) as ctx:
                parse_fn("select 1", "select", "cpp-json")
        message = str(ctx.exception)
        self.assertIn("HogQLParserShadowMismatch", message)
        self.assertIn("TEST=1", message)

    @parameterized.expand(_PARSE_HELPERS)
    def test_non_shadow_crash_is_bucketed_not_aborted(self, _name, parse_fn):
        with mock.patch.dict(_diagnostic_common._PARSER_FOR_RULE, {"select": _raise_runtime_error}):
            status, ast, detail = parse_fn("select 1", "select", "cpp-json")
        self.assertEqual(status, "crash")
        self.assertIsNone(ast)
        self.assertIn("half-built backend exploded", detail)

    def test_bench_aborts_on_shadow_mismatch(self):
        with self.assertRaises(SystemExit) as ctx:
            bench("smoke", _raise_shadow_mismatch, {"q1": "select 1"}, 1, 1, "cpp-json", "rust-json")
        self.assertIn("HogQLParserShadowMismatch", str(ctx.exception))
