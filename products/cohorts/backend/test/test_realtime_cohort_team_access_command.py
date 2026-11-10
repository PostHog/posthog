from datetime import UTC, datetime
from io import StringIO
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from parameterized import parameterized

from posthog.models.team.team import Team

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.team_access import (
    RealtimeCohortAccessPurpose,
    RealtimeCohortLevel,
    RealtimeCohortTeamAccess,
)

GRANTED_AT = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
PROMOTED_AT = datetime(2026, 10, 28, 13, 0, tzinfo=UTC)
REVOKED_AT = datetime(2026, 10, 28, 14, 0, tzinfo=UTC)


@override_settings(REALTIME_COHORT_TEAM_ALLOWLIST="none")
class TestRealtimeCohortTeamAccessCommand(BaseTest):
    def _access(self, team_id: int) -> RealtimeCohortTeamAccess:
        return RealtimeCohortTeamAccess.objects.get(team_id=team_id)

    def _grant(
        self, *team_ids: int, purpose: str = "load_test", level: str = "processing", triggers: bool = False
    ) -> None:
        teams = [str(team_id) for team_id in team_ids]
        call_command(
            "realtime_cohort_team_access",
            "grant",
            "--teams",
            *teams,
            "--purpose",
            purpose,
            "--level",
            level,
            "--save-triggers-backfill" if triggers else "--no-save-triggers-backfill",
        )

    def test_grant_promote_revoke_then_refuse_a_regrant(self) -> None:
        with time_machine.travel(GRANTED_AT, tick=False):
            self._grant(self.team.pk)
        with time_machine.travel(PROMOTED_AT, tick=False):
            self._grant(self.team.pk, level="serving", triggers=True)

        promoted = self._access(self.team.pk)
        assert (promoted.level, promoted.save_triggers_backfill, promoted.processing_since, promoted.off_since) == (
            RealtimeCohortLevel.SERVING,
            True,
            GRANTED_AT,
            None,
        )

        with time_machine.travel(REVOKED_AT, tick=False):
            call_command("realtime_cohort_team_access", "revoke", "--teams", str(self.team.pk))

        revoked = self._access(self.team.pk)
        assert (revoked.level, revoked.processing_since, revoked.off_since) == (
            RealtimeCohortLevel.OFF,
            GRANTED_AT,
            REVOKED_AT,
        )

        with self.assertRaisesMessage(
            CommandError, f"Revoked, and its pipeline state was never purged: {self.team.pk}"
        ):
            self._grant(self.team.pk)
        assert self._access(self.team.pk).level == RealtimeCohortLevel.OFF

        out = StringIO()
        call_command("realtime_cohort_team_access", "list", stdout=out)
        assert f"{self.team.pk}\toff\tload_test\tTrue" in out.getvalue()

    @parameterized.expand([("first_grant", None), ("promotion", "processing"), ("revoke", "serving")])
    @override_settings(FLAGS_REDIS_URL="redis://localhost:6379")
    def test_level_changes_refresh_the_team_metadata_cache(self, change: str, existing_level: str | None) -> None:
        if existing_level is not None:
            self._grant(self.team.pk, level=existing_level)

        with patch("posthog.tasks.team_metadata.update_team_metadata_cache_task") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                if change == "revoke":
                    call_command("realtime_cohort_team_access", "revoke", "--teams", str(self.team.pk))
                else:
                    self._grant(self.team.pk, level="serving")

        mock_task.delay.assert_called_once_with(self.team.pk)

    @parameterized.expand(
        [
            ("unknown_team", "No team with id"),
            ("child_environment", "Not a root team"),
            # The load test's stop command revokes by purpose, so it must never reach a pilot.
            ("granted_pilot", "Granted for another purpose than load_test"),
            # `revoke` refuses a listed team, so its row would block the stop command for every team.
            ("env_listed", "On REALTIME_COHORT_TEAM_ALLOWLIST"),
        ]
    )
    def test_grant_refuses_every_team_when_one_is_refused(self, kind: str, message: str) -> None:
        allowlist = "none"
        if kind == "unknown_team":
            refused_id = 999_999_999
        elif kind == "child_environment":
            refused_id = Team.objects.create(organization=self.organization, parent_team=self.team).pk
        elif kind == "env_listed":
            refused_id = Team.objects.create(organization=self.organization).pk
            allowlist = str(refused_id)
        else:
            refused_id = Team.objects.create(organization=self.organization).pk
            RealtimeCohortTeamAccess.objects.create(
                team_id=refused_id, level=RealtimeCohortLevel.SERVING, purpose=RealtimeCohortAccessPurpose.PILOT
            )

        with (
            override_settings(REALTIME_COHORT_TEAM_ALLOWLIST=allowlist),
            self.assertRaisesMessage(CommandError, f"{message}: {refused_id}"),
        ):
            self._grant(self.team.pk, refused_id)

        assert not RealtimeCohortTeamAccess.objects.filter(team=self.team).exists()

    def test_revoke_refuses_a_team_the_env_list_keeps_on(self) -> None:
        RealtimeCohortTeamAccess.objects.create(
            team=self.team, level=RealtimeCohortLevel.SERVING, purpose=RealtimeCohortAccessPurpose.PILOT
        )

        with (
            override_settings(REALTIME_COHORT_TEAM_ALLOWLIST=str(self.team.pk)),
            self.assertRaisesMessage(CommandError, f"On REALTIME_COHORT_TEAM_ALLOWLIST: {self.team.pk}"),
        ):
            call_command("realtime_cohort_team_access", "revoke", "--purpose", "pilot")

        assert self._access(self.team.pk).level == RealtimeCohortLevel.SERVING

    @parameterized.expand(
        [
            (
                "grant",
                ["grant", "--teams", "{team}", "--purpose", "beta", "--level", "serving", "--save-triggers-backfill"],
            ),
            ("revoke", ["revoke", "--purpose", "beta"]),
        ]
    )
    def test_only_enable_writes_beta_rows(self, _name: str, args: list[str]) -> None:
        RealtimeCohortTeamAccess.objects.create(
            team=self.team, level=RealtimeCohortLevel.PROCESSING, purpose=RealtimeCohortAccessPurpose.BETA
        )

        with self.assertRaisesMessage(CommandError, "invalid choice: 'beta'"):
            call_command("realtime_cohort_team_access", *(arg.format(team=self.team.pk) for arg in args))

        assert self._access(self.team.pk).level == RealtimeCohortLevel.PROCESSING

    def test_revoke_by_purpose_leaves_other_purposes_on(self) -> None:
        pilot = Team.objects.create(organization=self.organization)
        RealtimeCohortTeamAccess.objects.create(
            team=self.team, level=RealtimeCohortLevel.PROCESSING, purpose=RealtimeCohortAccessPurpose.LOAD_TEST
        )
        RealtimeCohortTeamAccess.objects.create(
            team=pilot, level=RealtimeCohortLevel.SERVING, purpose=RealtimeCohortAccessPurpose.PILOT
        )

        call_command("realtime_cohort_team_access", "revoke", "--purpose", "load_test")

        assert (self._access(self.team.pk).level, self._access(pilot.pk).level) == (
            RealtimeCohortLevel.OFF,
            RealtimeCohortLevel.SERVING,
        )

    @override_settings(
        BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED=True,
        BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED=True,
        BEHAVIORAL_BACKFILL_PERSON_SIZING_ATTESTED=True,
        BEHAVIORAL_BACKFILL_PERSON_TTL_ATTESTED=True,
        BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET=1_000_000,
    )
    @patch(
        "products.cohorts.backend.realtime_enablement.estimate_behavioral_scan_events",
        side_effect=RuntimeError("ClickHouse timeout"),
    )
    def test_enable_handles_each_team_and_fails_when_one_is_not_enabled(self, _scan_estimate: Any) -> None:
        held, serving, enabled = (Team.objects.create(organization=self.organization) for _ in range(3))
        env_listed_cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "person", "key": "email", "operator": "exact", "value": "person@example.com"}],
                }
            },
        )
        Cohort.objects.filter(id=env_listed_cohort.id).update(condition_type=None)
        held_cohort = Cohort.objects.create(
            team=held,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_value": 7,
                            "time_interval": "day",
                        }
                    ],
                }
            },
        )
        Cohort.objects.filter(id=held_cohort.id).update(last_backfill_events_at=datetime(2026, 1, 1, tzinfo=UTC))
        RealtimeCohortTeamAccess.objects.create(
            team=serving, level=RealtimeCohortLevel.SERVING, purpose=RealtimeCohortAccessPurpose.BETA
        )

        out = StringIO()
        with (
            override_settings(REALTIME_COHORT_TEAM_ALLOWLIST=str(self.team.pk)),
            self.assertRaisesMessage(CommandError, f"Not enabled: {self.team.pk}, {held.pk}."),
        ):
            teams = [str(team.pk) for team in (enabled, serving, held, self.team)]
            call_command("realtime_cohort_team_access", "enable", "--teams", *teams, stdout=out)

        output = out.getvalue()
        assert f"Team {self.team.pk}: refused, On REALTIME_COHORT_TEAM_ALLOWLIST: {self.team.pk}" in output
        assert f"Team {serving.pk}: already serving" in output
        assert f"Team {held.pk}: processing\n  Cleared old readiness stamps: 1 cohorts\n" in output
        assert Cohort.objects.get(id=env_listed_cohort.id).condition_type is None
        assert [self._access(team.pk).level for team in (held, serving, enabled)] == [
            RealtimeCohortLevel.PROCESSING,
            RealtimeCohortLevel.SERVING,
            RealtimeCohortLevel.SERVING,
        ]
