import os
import importlib

from posthog.test.base import BaseTest
from unittest import mock

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

import posthog.settings.cohorts as cohorts_settings

from products.cohorts.backend.models.team_access import (
    RealtimeCohortAccessPurpose,
    RealtimeCohortLevel,
    RealtimeCohortTeamAccess,
)
from products.cohorts.backend.realtime_teams import (
    backfill_triggers_suppressed,
    is_cohort_backfill_trigger_team,
    is_processing_team,
    is_serving_team,
    realtime_allowlist_matches,
)


class TestRealtimeAllowlistMatches(SimpleTestCase):
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
            self.assertEqual(realtime_allowlist_matches(team_id), expected)


class TestRealtimeLevel(BaseTest):
    @parameterized.expand(
        [
            ("no_row", "none", None, (False, False)),
            ("revoked_row", "none", RealtimeCohortLevel.OFF, (False, False)),
            # A load-test team runs the pipeline while its users see none of it.
            ("processing_row", "none", RealtimeCohortLevel.PROCESSING, (True, False)),
            ("serving_row", "none", RealtimeCohortLevel.SERVING, (True, True)),
            # The env list gated the screens users see before the levels existed, so it keeps doing so.
            ("env_listed_without_row", "team", None, (True, True)),
            ("env_listed_over_processing_row", "team", RealtimeCohortLevel.PROCESSING, (True, True)),
        ]
    )
    def test_level_is_the_union_of_env_list_and_row(
        self, _name: str, allowlist: str, level: RealtimeCohortLevel | None, expected: tuple[bool, bool]
    ) -> None:
        if level is not None:
            RealtimeCohortTeamAccess.objects.create(
                team=self.team, level=level, purpose=RealtimeCohortAccessPurpose.PILOT
            )

        with override_settings(REALTIME_COHORT_TEAM_ALLOWLIST=str(self.team.pk) if allowlist == "team" else allowlist):
            processing, serving = expected
            self.assertEqual(
                (
                    is_processing_team(self.team.pk),
                    is_processing_team(self.team.pk, fresh=True),
                    is_serving_team(self.team.pk),
                ),
                (processing, processing, serving),
            )


class TestIsCohortBackfillTriggerTeam(BaseTest):
    @parameterized.expand(
        [
            # Only Python parses this setting, so unlike the realtime allowlist it fails closed on a
            # set-but-empty value, the natural Helm rendering of "clear this".
            ("empty_fails_closed", "", 2, False),
            ("whitespace_fails_closed", "   ", 2, False),
            ("all_keyword", "all", 2, True),
            ("single_match", "2", 2, True),
            ("single_miss", "2", 3, False),
        ]
    )
    def test_membership(self, _name: str, allowlist: str, team_id: int, expected: bool) -> None:
        with override_settings(COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST=allowlist):
            self.assertEqual(is_cohort_backfill_trigger_team(team_id), expected)

    @parameterized.expand(
        [
            ("granted_with_triggers", RealtimeCohortLevel.PROCESSING, True, True),
            ("granted_without_triggers", RealtimeCohortLevel.PROCESSING, False, False),
            ("revoked_with_triggers", RealtimeCohortLevel.OFF, True, False),
        ]
    )
    @override_settings(COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST="none")
    def test_row_triggers_only_while_granted(
        self, _name: str, level: RealtimeCohortLevel, save_triggers_backfill: bool, expected: bool
    ) -> None:
        RealtimeCohortTeamAccess.objects.create(
            team=self.team,
            level=level,
            purpose=RealtimeCohortAccessPurpose.LOAD_TEST,
            save_triggers_backfill=save_triggers_backfill,
        )

        self.assertEqual(is_cohort_backfill_trigger_team(self.team.pk), expected)

    @override_settings(COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST="all")
    def test_suppression_overrides_every_trigger_source(self) -> None:
        RealtimeCohortTeamAccess.objects.create(
            team=self.team,
            level=RealtimeCohortLevel.PROCESSING,
            purpose=RealtimeCohortAccessPurpose.LOAD_TEST,
            save_triggers_backfill=True,
        )

        with backfill_triggers_suppressed():
            self.assertFalse(is_cohort_backfill_trigger_team(self.team.pk))
        self.assertTrue(is_cohort_backfill_trigger_team(self.team.pk))


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
