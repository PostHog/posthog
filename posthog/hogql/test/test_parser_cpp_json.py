import gc
import tracemalloc

from posthog.test.base import BaseTest

from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_program

from ._test_parser import parser_test_factory


class TestParserCppJson(parser_test_factory("cpp-json")):  # type: ignore
    def test_empty(self):
        # this test only exists to make pycharm recognise this class as a test class
        # the actual tests are in the parent class
        pass


class TestCppParserRejectNoLeak(BaseTest):
    def test_reject_path_does_not_leak(self):
        # The cpp parser's error path returns a JSON error envelope (deserialize_ast then raises) instead of raising a Python exception built in C, which used to leak the (often large) ANTLR "expecting {...}" message string on every rejected parse. Measured with tracemalloc rather than the page-granular ru_maxrss leak mixin, which missed this leak on Linux CI (it only tripped on macOS's 16 KiB pages). Threshold sits far below the ~1 KB/parse the leak produced and far above the <1 B/parse steady state.
        def reject() -> None:
            try:
                parse_program("let null := 1", backend="cpp-json")
            except ExposedHogQLError:
                pass

        for _ in range(200):  # saturate one-time caches before measuring
            reject()
        gc.collect()
        was_tracing = tracemalloc.is_tracing()
        if not was_tracing:
            tracemalloc.start(1)
        before = tracemalloc.take_snapshot()
        runs = 500
        for _ in range(runs):
            reject()
        gc.collect()
        after = tracemalloc.take_snapshot()
        per_parse = sum(stat.size_diff for stat in after.compare_to(before, "filename")) / runs
        if not was_tracing:
            tracemalloc.stop()
        self.assertLess(
            per_parse, 100, f"cpp-json reject path leaked {per_parse:.0f} B/parse (regressed; was ~1000 B/parse)"
        )
