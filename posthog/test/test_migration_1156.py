from typing import Any

import pytest
from posthog.test.base import NonAtomicTestMigrations

from parameterized import parameterized

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class RemovePresortedEventsModifierFromTeamMigrationTest(NonAtomicTestMigrations):
    migrate_from = "1155_sharingconfiguration_interviewee_context"
    migrate_to = "1156_remove_presorted_events_modifier_team"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")

        self.organization = Organization.objects.create(name="Test Organization")
        self.project = Project.objects.create(organization=self.organization, name="Test Project", id=1000001)
        self.Team = Team

        self.teams = {}

        self.teams["only_presorted"] = Team.objects.create(
            organization=self.organization,
            project=self.project,
            name="Only presorted",
            modifiers={"usePresortedEventsTable": True},
        )

        self.teams["presorted_with_others"] = Team.objects.create(
            organization=self.organization,
            project=self.project,
            name="Presorted with others",
            modifiers={"usePresortedEventsTable": False, "inCohortVia": "subquery"},
        )

        self.teams["no_presorted"] = Team.objects.create(
            organization=self.organization,
            project=self.project,
            name="No presorted",
            modifiers={"inCohortVia": "subquery"},
        )

        self.teams["empty_modifiers"] = Team.objects.create(
            organization=self.organization,
            project=self.project,
            name="Empty modifiers",
            modifiers={},
        )

        self.teams["null_modifiers"] = Team.objects.create(
            organization=self.organization,
            project=self.project,
            name="Null modifiers",
            modifiers=None,
        )

    @parameterized.expand(
        [
            ("only_presorted", {}),
            ("presorted_with_others", {"inCohortVia": "subquery"}),
            ("no_presorted", {"inCohortVia": "subquery"}),
            ("empty_modifiers", {}),
            ("null_modifiers", None),
        ]
    )
    def test_presorted_events_modifier_removed_from_team(self, team_key, expected_modifiers):
        team = self.teams[team_key]
        team.refresh_from_db()

        self.assertEqual(team.modifiers, expected_modifiers)
