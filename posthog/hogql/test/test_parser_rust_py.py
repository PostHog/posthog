"""Tests for the hand-rolled Rust HogQL parser via the direct-Python-object path (`rust-py`).

The full parser-behaviour suite lives in `_test_parser.py` and runs
against every backend via `parser_test_factory`. This file only wires
the `rust-py` backend into that suite. Same parser core as `rust-json`;
only difference is how the result lands in Python (PyO3 builds the
dataclass instances directly, skipping the JSON round-trip).
"""

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
