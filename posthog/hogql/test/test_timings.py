from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.hogql.timings import HogQLTimings

EPSILON = 1e-10
counter_values: list[float] = [0]


def fake_perf_counter():
    counter_values[0] += 0.05
    return counter_values[0]


class TestHogQLTimings(BaseTest):
    def setUp(self):
        counter_values[0] = 0

    def test_basic_timing(self):
        with patch("posthog.hogql.timings.perf_counter", fake_perf_counter):
            timings = HogQLTimings()

            with timings.measure("test"):
                pass

            results = timings.to_dict()
            self.assertAlmostEqual(results["./test"], 0.05)
            self.assertAlmostEqual(results["."], 0.15)

    def test_no_timing(self):
        with patch("posthog.hogql.timings.perf_counter", fake_perf_counter):
            timings = HogQLTimings()

            results = timings.to_dict()
            self.assertEqual(results, {".": 0.05})

    def test_nested_timing(self):
        with patch("posthog.hogql.timings.perf_counter", fake_perf_counter):
            timings = HogQLTimings()

            with timings.measure("outer"):
                with timings.measure("inner"):
                    pass

            results = timings.to_dict()
            self.assertAlmostEqual(results["./outer/inner"], 0.05)
            self.assertAlmostEqual(results["./outer"], 0.15)
            self.assertAlmostEqual(results["."], 0.25)

    def test_multiple_top_level_timings(self):
        with patch("posthog.hogql.timings.perf_counter", fake_perf_counter):
            timings = HogQLTimings()

            with timings.measure("first"):
                pass
            with timings.measure("second"):
                pass

            results = timings.to_dict()
            self.assertAlmostEqual(results["./first"], 0.05)
            self.assertAlmostEqual(results["./second"], 0.05)
            self.assertAlmostEqual(results["."], 0.25)

    def test_deeply_nested_timing(self):
        with patch("posthog.hogql.timings.perf_counter", fake_perf_counter):
            timings = HogQLTimings()

            with timings.measure("a"):
                with timings.measure("b"):
                    with timings.measure("c"):
                        pass

            results = timings.to_dict()
            self.assertAlmostEqual(results["./a/b/c"], 0.05)
            self.assertAlmostEqual(results["./a/b"], 0.15)
            self.assertAlmostEqual(results["./a"], 0.25)
            self.assertAlmostEqual(results["."], 0.35)

    def test_overlapping_keys(self):
        with patch("posthog.hogql.timings.perf_counter", fake_perf_counter):
            timings = HogQLTimings()

            with timings.measure("a"):
                pass
            with timings.measure("a"):
                pass

            results = timings.to_dict()
            self.assertAlmostEqual(results["./a"], 0.1)
            self.assertAlmostEqual(results["."], 0.25)
