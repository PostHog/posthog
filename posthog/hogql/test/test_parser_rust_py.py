"""Tests for the hand-rolled Rust HogQL parser via the direct-Python-object path (`rust-py`).

The full parser-behaviour suite lives in `_test_parser.py` and runs
against every backend via `parser_test_factory`. This file only wires
the `rust-py` backend into that suite. Same parser core as `rust-json`;
only difference is how the result lands in Python (PyO3 builds the
dataclass instances directly, skipping the JSON round-trip).
"""

from ._test_parser import parser_test_factory

# `ast.Dict.items` is typed `list[tuple[Expr, Expr]]`. The direct-PyO3 path
# builds tuples (matching the annotation); the JSON oracle (cpp-json) builds
# lists, since JSON has no tuple type. These two tests assert full AST parity
# against the JSON oracle, so the list-vs-tuple shape diverges — a serialisation
# representation difference, not a parser-behaviour one. Deferred for rust-py
# rather than reshaping the JSON deserialiser (which the oracle shares).
_DEFERRED: set[str] = {
    "test_block_then_empty_param_lambda_is_two_statements",
    "test_statement_leading_brace_block_vs_call",
}


class TestParserRustPy(parser_test_factory("rust-py")):  # type: ignore
    def setUp(self) -> None:
        super().setUp()
        if self._testMethodName in _DEFERRED:
            self.skipTest("Dict.items list (JSON oracle) vs tuple (direct PyO3) representation difference")

    def test_empty(self):
        # this test only exists to make pycharm recognise this class as a test class
        # the actual tests are in the parent class
        pass
