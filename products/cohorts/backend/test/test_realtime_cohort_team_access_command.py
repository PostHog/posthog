from datetime import UTC, datetime
from io import StringIO

import time_machine
from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from parameterized import parameterized

from posthog.models.team.team import Team

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
