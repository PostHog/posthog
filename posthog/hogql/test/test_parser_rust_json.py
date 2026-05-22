"""Tests for the hand-rolled Rust HogQL parser (`rust-json` backend).

The full parser-behaviour suite lives in `_test_parser.py` and runs
against every backend via `parser_test_factory`. This file only wires
the `rust-json` backend into that suite and lists the cases the Rust
parser does not yet match the C++ reference on.
"""

from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_expr

from ._test_parser import parser_test_factory

# Cases the Rust parser does not yet match C++ on, tracked for follow-up:
#   - promoted_assignment_target_carries_position: the Rust parser does
#     not yet emit per-node source positions (`start` / `end`) at all —
#     every node comes back position-less. The shared suite tolerates
#     this via `clear_locations`, but this test inspects raw positions.
#     Closing it means threading byte offsets through the whole emit
#     layer — a feature in its own right, not a local fix.
_DEFERRED_EXACT: set[str] = {
    "test_promoted_assignment_target_carries_position",
}


class TestParserRustJson(parser_test_factory("rust-json")):  # type: ignore
    def setUp(self) -> None:
        super().setUp()
        if self._testMethodName in _DEFERRED_EXACT:
            self.skipTest("not yet matched by rust-json")

    def test_empty(self):
        # this test only exists to make pycharm recognise this class as a test class
        # the actual tests are in the parent class
        pass

    def test_invalid_interval_in_block_body_rejected(self):
        # Once `interval` is followed by a primary value it commits to the INTERVAL
        # form: a missing / bad unit is a hard error, never a fall-back to
        # `interval`-as-Field. Inside a Hog `{ … }` block body the fall-back would
        # strand the string as a second statement, so `x -> { interval 'ln' }` would
        # parse as `interval; 'ln'` — accepting input the cpp oracle rejects.
        for backend in ("cpp-json", "rust-json"):
            with self.assertRaises(BaseHogQLError):
                parse_expr("x -> { interval 'ln' }", backend=backend)
