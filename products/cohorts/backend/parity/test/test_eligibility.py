import json
import math
from datetime import date
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.parity.eligibility import behavioral_history_over_limit, screen_team

_FIXTURE = Path(__file__).parent / "fixtures" / "eligibility_golden.json"
_CASES = json.loads(_FIXTURE.read_text())["cases"]


class TestEligibilityGoldenVectors(SimpleTestCase):
    def test_long_acyclic_ref_chain_does_not_hit_recursion_limit(self) -> None:
        chain_length = 2000  # comfortably past Python's default recursion limit
        cohorts: dict[int, dict] = {
            cid: {"properties": {"type": "AND", "values": [{"type": "cohort", "key": "id", "value": cid + 1}]}}
            for cid in range(1, chain_length)
        }
        cohorts[chain_length] = {
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "person",
                        "key": "email",
                        "value": "a@b.com",
                        "conditionHash": "aaaaaaaaaaaaaaaa",
                        "bytecode": ["_H", 1],
                    }
                ],
            }
        }
        screened = screen_team(cohorts, cascade_enabled=True)
        self.assertEqual(screened[1].eligibility, "stage2_composable_ref")
        self.assertEqual(screened[chain_length].eligibility, "single_leaf")

    @parameterized.expand([(case["name"], case) for case in _CASES])
    def test_golden_vector(self, _name: str, case: dict) -> None:
        cohorts = {1: case["filters"]}
        for cid, filters in case.get("extra_cohorts", {}).items():
            cohorts[int(cid)] = filters
        screened = screen_team(cohorts, cascade_enabled=case.get("cascade_enabled", True))

        self.assertEqual(screened[1].eligibility, case["expected"])
        if "expected_window_days" in case:
            expected = case["expected_window_days"]
            if expected == "inf":
                self.assertEqual(screened[1].max_window_days, math.inf)
            elif expected is None:
                self.assertIsNone(screened[1].max_window_days)
            else:
                self.assertEqual(screened[1].max_window_days, expected)


def _behavioral(**window: object) -> dict:
    return {"type": "behavioral", "key": "$pageview", "event_type": "events", "value": "performed_event", **window}


def _and(*values: dict) -> dict:
    return {"type": "AND", "values": list(values)}


class TestBehavioralHistoryOverLimit(SimpleTestCase):
    @parameterized.expand(
        [
            ("sliding_at_the_limit", _behavioral(time_value=400, time_interval="day"), False),
            ("sliding_past_the_limit", _behavioral(time_value=401, time_interval="day"), True),
            ("thirteen_months_of_thirty_days", _behavioral(time_value=13, time_interval="month"), False),
            ("relative_start", _behavioral(explicit_datetime="-2y"), True),
            ("absolute_start_at_the_limit", _behavioral(explicit_datetime="2025-10-01"), False),
            # The written date is 401 days back; read in UTC it would be 400.
            ("absolute_start_past_the_limit", _behavioral(explicit_datetime="2025-09-30T23:00:00-05:00"), True),
            ("range_with_only_an_end", _behavioral(explicit_datetime_to="2026-01-01"), True),
            ("sub_day_window", _behavioral(time_value=10_000, time_interval="hour"), False),
            (
                "nested_leaf_past_the_limit",
                _and(
                    {
                        "type": "OR",
                        "values": [
                            _behavioral(time_value=7, time_interval="day"),
                            _behavioral(time_value=2, time_interval="year"),
                        ],
                    }
                ),
                True,
            ),
        ]
    )
    def test_history_over_limit(self, _name: str, properties: dict, expected: bool) -> None:
        self.assertEqual(
            behavioral_history_over_limit(properties, limit_days=400, today=date(2026, 11, 5)),
            expected,
        )
