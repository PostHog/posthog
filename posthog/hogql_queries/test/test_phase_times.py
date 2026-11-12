from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql_queries.phase_times import compute_phase_times


class TestComputePhaseTimes(SimpleTestCase):
    def test_runner_tree_rollups_convert_to_ms_and_default_none_when_absent(self) -> None:
        result = compute_phase_times({"./rate_limiters": 0.012, "./cache_write": 0.003, "./query": 0.5})
        self.assertEqual(
            result,
            {"rate_limiters_ms": 12.0, "cache_write_ms": 3.0, "flight_wait_ms": None, "build_database_ms": None},
        )

    def test_a_second_run_reports_only_what_it_added_to_the_tree(self) -> None:
        first_run = {"./rate_limiters": 0.012, "./cache_write": 0.003}
        result = compute_phase_times(
            {"./rate_limiters": 0.020, "./cache_write": 0.003, "./flight_wait": 0.1}, before=first_run
        )
        self.assertEqual(
            result,
            {"rate_limiters_ms": 8.0, "cache_write_ms": None, "flight_wait_ms": 100.0, "build_database_ms": None},
        )

    @parameterized.expand(
        [
            ("at_the_root", {"./build_shared_database": 1.8, "./build_shared_database/team": 0.1}, {}, 1800.0),
            ("inside_another_phase", {"./filters/build_shared_database": 1.8}, {}, 1800.0),
            (
                "in_two_places",
                {"./build_shared_database": 1.0, "./filters/build_shared_database": 0.5},
                {},
                1500.0,
            ),
            (
                "only_what_this_run_added",
                {"./build_shared_database": 1.0, "./filters/build_shared_database": 0.7},
                {"./build_shared_database": 1.0, "./filters/build_shared_database": 0.5},
                200.0,
            ),
        ]
    )
    def test_the_database_build_adds_up_every_place_the_run_built_it(
        self, _name: str, runner_timings: dict[str, float], before: dict[str, float], expected_ms: float
    ) -> None:
        assert compute_phase_times(runner_timings, before=before)["build_database_ms"] == expected_ms
