"""Tests for the hand-rolled Rust HogQL parser (`rust-json` backend).

The full parser-behaviour suite lives in `_test_parser.py` and runs
against every backend via `parser_test_factory`. This file only wires
the `rust-json` backend into that suite.
"""

from ._test_parser import parser_test_factory


class TestParserRustJson(parser_test_factory("rust-json")):  # type: ignore
    def test_empty(self):
        # this test only exists to make pycharm recognise this class as a test class
        # the actual tests are in the parent class
        pass
