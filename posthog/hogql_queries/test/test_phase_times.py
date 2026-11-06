from django.test import SimpleTestCase

from posthog.hogql_queries.phase_times import compute_phase_times


class TestComputePhaseTimes(SimpleTestCase):
    def test_runner_tree_rollups_convert_to_ms_and_default_none_when_absent(self) -> None:
        result = compute_phase_times({"./rate_limiters": 0.012, "./cache_write": 0.003, "./query": 0.5})
        self.assertEqual(result, {"rate_limiters_ms": 12.0, "cache_write_ms": 3.0, "flight_wait_ms": None})

    def test_a_second_run_reports_only_what_it_added_to_the_tree(self) -> None:
        first_run = {"./rate_limiters": 0.012, "./cache_write": 0.003}
        result = compute_phase_times(
            {"./rate_limiters": 0.020, "./cache_write": 0.003, "./flight_wait": 0.1}, before=first_run
        )
        self.assertEqual(result, {"rate_limiters_ms": 8.0, "cache_write_ms": None, "flight_wait_ms": 100.0})
