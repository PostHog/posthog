"""Tests for the hand-rolled Rust HogQL parser via the direct-Python-object path (`rust-py`).

The full parser-behaviour suite lives in `_test_parser.py` and runs
against every backend via `parser_test_factory`. This file only wires
the `rust-py` backend into that suite. Same parser core as `rust-json`;
only difference is how the result lands in Python (PyO3 builds the
dataclass instances directly, skipping the JSON round-trip).
"""

from unittest.mock import patch

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_select

from ._test_parser import parser_test_factory

# Same deferral as `rust-json`: PyEmitter's `with_pos` chain doesn't yet
# propagate positions onto the promoted assignment target node. Underlying
# parser logic is shared, so the gap is wired in `with_pos` rather than
# in the per-backend AST shape.
_DEFERRED_EXACT: set[str] = {
    "test_promoted_assignment_target_carries_position",
}


class TestParserRustPy(parser_test_factory("rust-py")):  # type: ignore
    def setUp(self) -> None:
        super().setUp()
        if self._testMethodName in _DEFERRED_EXACT:
            self.skipTest("not yet matched by rust-py")

    def test_empty(self):
        # this test only exists to make pycharm recognise this class as a test class
        # the actual tests are in the parent class
        pass

    def test_dataclass_post_init_failure_surfaces_as_hogql_error(self):
        # Regression: PyEmitter.build calls `class(**kwargs)` directly and panicked on dataclass `__post_init__` rejection (e.g. JoinExpr's VALID_JOIN_TYPES check). PyO3 caught the panic as PanicException — not a SIGSEGV, but still the wrong shape for production handlers that catch the ExposedHogQLError family. lib.rs now wraps the emitter drive in catch_unwind and re-emits as NotImplementedError. `mock.patch.object` is the lint-clean way to swap the dataclass method for the duration of the parse call.
        def always_reject(_self: ast.JoinExpr) -> None:
            raise ValueError("synthetic post_init failure for test")

        with patch.object(ast.JoinExpr, "__post_init__", always_reject):
            with self.assertRaises(BaseHogQLError) as caught:
                parse_select("SELECT 1 FROM a JOIN b ON a.x = b.x", backend="rust-py")
        # The PanicException base is `BaseException`, not Exception — if catch_unwind didn't fire we'd see PanicException leak through, not a HogQLError subclass.
        self.assertIn("synthetic post_init failure", str(caught.exception))
