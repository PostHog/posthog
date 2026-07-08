import json
import math
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.parity.eligibility import screen_team

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
