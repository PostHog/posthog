from typing import Any

import pytest
from posthog.test.base import TestMigrations

from parameterized import parameterized

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class FixNonListTestAccountFiltersMigrationTest(TestMigrations):
    migrate_from = "1184_migrate_product_analytics_models"
    migrate_to = "1185_fix_non_list_test_account_filters"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")

        self.organization = Organization.objects.create(name="Test Organization")
        self.project = Project.objects.create(organization=self.organization, name="Test Project", id=1_000_001)
        self.Team = Team

        # JSONField encodes whatever Python value we pass via json.dumps, so a Python str
        # becomes a JSON string in the column - the exact corruption we are repairing.
        self.teams = {
            "stringified_array": self._create_team(
                "stringified_array",
                test_account_filters='[{"key":"$browser","value":"Chrome","operator":"exact"}]',
            ),
            "stringified_non_array": self._create_team(
                "stringified_non_array",
                test_account_filters="not even an array",
            ),
            "object": self._create_team(
                "object",
                test_account_filters={"key": "$browser", "value": "Chrome"},
            ),
            "json_null": self._create_team(
                "json_null",
                test_account_filters=None,
            ),
            "already_array": self._create_team(
                "already_array",
                test_account_filters=[{"key": "email", "value": "@posthog.com", "operator": "icontains"}],
            ),
        }

    def _create_team(self, name: str, test_account_filters: Any) -> Any:
        return self.Team.objects.create(
            organization=self.organization,
            project=self.project,
            name=name,
            test_account_filters=test_account_filters,
        )

    @parameterized.expand(
        [
            # Stringified JSON array - the meaningful recovery, preserve the parsed contents.
            (
                "stringified_array",
                [{"key": "$browser", "value": "Chrome", "operator": "exact"}],
            ),
            # Stringified non-array - cannot recover, reset to [].
            ("stringified_non_array", []),
            # JSON object - reset to [].
            ("object", []),
            # JSON null - reset to [].
            ("json_null", []),
            # Already a valid array - left untouched.
            (
                "already_array",
                [{"key": "email", "value": "@posthog.com", "operator": "icontains"}],
            ),
        ]
    )
    def test_test_account_filters_normalized(self, team_key: str, expected: list) -> None:
        team = self.teams[team_key]
        team.refresh_from_db()
        self.assertEqual(team.test_account_filters, expected)
