from typing import Any

from posthog.test.base import TestMigrations

from django.test import override_settings

from posthog.models.team.team import Team

from products.cohorts.backend.models.team_access import RealtimeCohortLevel


class TestTurnOnRealtimeForProcessedTeams(TestMigrations):
    app = "cohorts"
    migrate_from = "0022_cohort_realtime_enabled_at"
    migrate_to = "0023_turn_on_realtime_for_processed_teams"

    def setUp(self) -> None:
        self.env_listed, self.processing, self.revoked, self.rowless = (
            Team.objects.create(organization=self.organization) for _ in range(4)
        )
        with override_settings(REALTIME_COHORT_TEAM_ALLOWLIST=str(self.env_listed.id)):
            super().setUp()

    def setUpBeforeMigration(self, apps: Any) -> None:
        Cohort = apps.get_model("cohorts", "Cohort")
        RealtimeCohortTeamAccess = apps.get_model("cohorts", "RealtimeCohortTeamAccess")
        RealtimeCohortTeamAccess.objects.create(
            team_id=self.processing.id, level=RealtimeCohortLevel.PROCESSING, purpose="beta"
        )
        RealtimeCohortTeamAccess.objects.create(team_id=self.revoked.id, level=RealtimeCohortLevel.OFF, purpose="beta")

        def cohort(team: Team, cohort_type: str | None = "realtime", deleted: bool = False) -> int:
            return Cohort.objects.create(team_id=team.id, cohort_type=cohort_type, deleted=deleted).id

        self.turned_on = {cohort(self.env_listed), cohort(self.processing), cohort(self.processing, deleted=True)}
        self.left_off = {cohort(self.env_listed, cohort_type=None), cohort(self.revoked), cohort(self.rowless)}

    def test_turns_on_the_realtime_cohorts_of_processed_teams_only(self) -> None:
        Cohort = self.apps.get_model("cohorts", "Cohort")  # type: ignore[union-attr]

        on = set(
            Cohort.objects.filter(id__in=self.turned_on | self.left_off, realtime_enabled_at__isnull=False).values_list(
                "id", flat=True
            )
        )
        assert on == self.turned_on
