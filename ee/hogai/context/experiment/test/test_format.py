from unittest import TestCase

from ee.hogai.context.experiment.format import ExperimentTimeseriesFormatter


def _bayesian_day(
    *,
    control_n: int = 1000,
    control_sum: float = 50,
    test_n: int = 1010,
    test_sum: float = 70,
    chance_to_win: float | None = 0.92,
    significant: bool | None = True,
    credible_interval: list[float] | None = None,
) -> dict:
    return {
        "baseline": {
            "key": "control",
            "number_of_samples": control_n,
            "sum": control_sum,
            "sum_squares": control_sum * 2,
        },
        "variant_results": [
            {
                "key": "test",
                "method": "bayesian",
                "number_of_samples": test_n,
                "sum": test_sum,
                "sum_squares": test_sum * 2,
                "chance_to_win": chance_to_win,
                "credible_interval": credible_interval or [0.01, 0.05],
                "significant": significant,
            }
        ],
    }


class TestExperimentTimeseriesFormatter(TestCase):
    def test_empty_timeseries(self):
        result = ExperimentTimeseriesFormatter({"timeseries": {}}).format()
        self.assertEqual(result, "No timeseries data.")

    def test_all_days_pending(self):
        response = {
            "status": "pending",
            "timeseries": {"2026-04-01": None, "2026-04-02": None},
        }
        self.assertEqual(
            ExperimentTimeseriesFormatter(response).format(),
            "No completed timeseries data (status: pending).",
        )

    def test_bayesian_two_days(self):
        response = {
            "status": "completed",
            "timeseries": {
                "2026-04-01": _bayesian_day(),
                "2026-04-02": _bayesian_day(test_sum=80, chance_to_win=0.97),
            },
        }
        out = ExperimentTimeseriesFormatter(response).format()
        lines = out.splitlines()
        self.assertEqual(lines[0], "Method: bayesian")
        self.assertEqual(lines[1], "Variants: control (baseline), test")
        self.assertEqual(lines[2], "Status: completed")
        self.assertEqual(
            lines[3],
            "Date|control n|control mean|test n|test mean|test interval|test chance_to_win|test significant",
        )
        self.assertEqual(lines[4], "2026-04-01|1000|0.05|1010|0.069307|0.01..0.05|0.92|true")
        self.assertEqual(lines[5], "2026-04-02|1000|0.05|1010|0.079208|0.01..0.05|0.97|true")

    def test_skips_null_days(self):
        response = {
            "status": "partial",
            "timeseries": {
                "2026-04-01": _bayesian_day(),
                "2026-04-02": None,
                "2026-04-03": _bayesian_day(test_sum=90, chance_to_win=0.99),
            },
        }
        out = ExperimentTimeseriesFormatter(response).format()
        lines = out.splitlines()
        self.assertEqual(lines[5], "2026-04-02|—")
        self.assertTrue(lines[6].startswith("2026-04-03|"))

    def test_frequentist_uses_p_value_and_confidence_interval(self):
        response = {
            "status": "completed",
            "timeseries": {
                "2026-04-01": {
                    "baseline": {"key": "control", "number_of_samples": 800, "sum": 40},
                    "variant_results": [
                        {
                            "key": "test",
                            "method": "frequentist",
                            "number_of_samples": 820,
                            "sum": 60,
                            "p_value": 0.012,
                            "confidence_interval": [0.005, 0.04],
                            "significant": True,
                        }
                    ],
                },
            },
        }
        out = ExperimentTimeseriesFormatter(response).format()
        lines = out.splitlines()
        self.assertEqual(lines[0], "Method: frequentist")
        self.assertIn("test p_value", lines[3])
        self.assertEqual(lines[4], "2026-04-01|800|0.05|820|0.073171|0.005..0.04|0.012|true")

    def test_handles_missing_variant_fields(self):
        response = {
            "status": "completed",
            "timeseries": {
                "2026-04-01": {
                    "baseline": {"key": "control", "number_of_samples": 0, "sum": 0},
                    "variant_results": [
                        {
                            "key": "test",
                            "method": "bayesian",
                            "number_of_samples": 0,
                            "sum": 0,
                            "chance_to_win": None,
                            "significant": None,
                        }
                    ],
                },
            },
        }
        out = ExperimentTimeseriesFormatter(response).format()
        lines = out.splitlines()
        self.assertEqual(lines[4], "2026-04-01|0|N/A|0|N/A|N/A|N/A|N/A")

    def test_multi_variant_ordering(self):
        response = {
            "status": "completed",
            "timeseries": {
                "2026-04-01": {
                    "baseline": {"key": "control", "number_of_samples": 1000, "sum": 50},
                    "variant_results": [
                        {
                            "key": "blue",
                            "method": "bayesian",
                            "number_of_samples": 1000,
                            "sum": 60,
                            "chance_to_win": 0.6,
                            "credible_interval": [0.0, 0.1],
                            "significant": False,
                        },
                        {
                            "key": "green",
                            "method": "bayesian",
                            "number_of_samples": 1010,
                            "sum": 80,
                            "chance_to_win": 0.95,
                            "credible_interval": [0.02, 0.08],
                            "significant": True,
                        },
                    ],
                },
            },
        }
        out = ExperimentTimeseriesFormatter(response).format()
        lines = out.splitlines()
        self.assertEqual(lines[1], "Variants: control (baseline), blue, green")
        self.assertIn("blue chance_to_win", lines[3])
        self.assertIn("green chance_to_win", lines[3])

    def test_step_sessions_are_ignored_when_present(self):
        day = _bayesian_day()
        day["baseline"]["step_sessions"] = [
            [{"event_uuid": "x", "person_id": "p", "session_id": "s", "timestamp": "t"}]
        ]
        day["variant_results"][0]["step_sessions"] = [
            [{"event_uuid": "x", "person_id": "p", "session_id": "s", "timestamp": "t"}]
        ]
        response = {"status": "completed", "timeseries": {"2026-04-01": day}}
        out = ExperimentTimeseriesFormatter(response).format()
        self.assertNotIn("step_sessions", out)
        self.assertNotIn("event_uuid", out)
