import os
import importlib

from unittest import mock

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

import posthog.settings.cohorts as cohorts_settings

from products.cohorts.backend.realtime_teams import is_realtime_cohort_team


class TestIsRealtimeCohortTeam(SimpleTestCase):
    @parameterized.expand(
        [
            ("all_keyword", "all", 999, True),
            ("all_uppercase", "ALL", 999, True),
            ("star", "*", 999, True),
            ("empty", "", 999, True),
            ("whitespace_only", "   ", 999, True),
            ("none_keyword", "none", 2, False),
            ("none_uppercase", "NONE", 2, False),
            ("single_match", "2", 2, True),
            ("single_miss", "2", 3, False),
            ("list_match", "2, 42 ,7", 42, True),
            ("list_miss", "2, 42 ,7", 8, False),
            ("range_low_bound", "1:3", 1, True),
            ("range_mid", "1:3", 2, True),
            ("range_high_bound", "1:3", 3, True),
            ("range_miss", "1:3", 4, False),
            ("range_and_id_hits_id", "1:2,5", 5, True),
            ("range_and_id_hits_range", "1:2,5", 1, True),
            ("max_span_range_ok", "1:100000", 100000, True),
            ("garbage", "nope", 2, False),
            ("inverted_range", "3:1", 2, False),
            ("oversized_range", "1:100002", 2, False),
            ("valid_id_beside_garbage", "2,x", 2, True),
        ]
    )
    def test_membership_matches_rust_grammar(self, _name: str, allowlist: str, team_id: int, expected: bool) -> None:
        with override_settings(REALTIME_COHORT_TEAM_ALLOWLIST=allowlist):
            self.assertEqual(is_realtime_cohort_team(team_id), expected)


class TestRealtimeCohortAllowlistSetting(SimpleTestCase):
    def _reload_allowlist(self) -> str:
        self.addCleanup(importlib.reload, cohorts_settings)
        importlib.reload(cohorts_settings)
        return cohorts_settings.REALTIME_COHORT_TEAM_ALLOWLIST

    def test_unset_defaults_to_off(self) -> None:
        with mock.patch.dict(os.environ):
            os.environ.pop("REALTIME_COHORT_TEAM_ALLOWLIST", None)
            self.assertEqual(self._reload_allowlist(), "none")

    def test_set_but_empty_value_is_preserved(self) -> None:
        with mock.patch.dict(os.environ, {"REALTIME_COHORT_TEAM_ALLOWLIST": ""}):
            self.assertEqual(self._reload_allowlist(), "")
