from typing import Any

from posthog.test.base import NonAtomicTestMigrations

from parameterized import parameterized


class RemoveNullValuesFromTeamArraysMigrationTest(NonAtomicTestMigrations):
    migrate_from = "0837_alter_externaldatasource_source_type"
    migrate_to = "0838_remove_null_values_from_team_arrays"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")

        self.organization = Organization.objects.create(name="Test Organization")
        self.project = Project.objects.create(organization=self.organization, name="Test Project", id=1000001)
        self.Team = Team

        # Create all test teams with specific test data before migration runs
        self.teams = {}

        # app_urls
        self.teams["app_mixed"] = self._create_team(
            "App mixed", app_urls=["https://valid.com", None, "https://valid2.com", None]
        )
        self.teams["app_all_nulls"] = self._create_team("App all nulls", app_urls=[None, None])
        self.teams["app_empty"] = self._create_team("App empty", app_urls=[])
        self.teams["app_clean"] = self._create_team("App clean", app_urls=["https://clean.com"])

        # recording_domains
        self.teams["rec_mixed"] = self._create_team(
            "Rec mixed", recording_domains=["domain1.com", None, "domain2.com", None]
        )
        self.teams["rec_all_nulls"] = self._create_team("Rec all nulls", recording_domains=[None, None])
        self.teams["rec_empty"] = self._create_team("Rec empty", recording_domains=[])
        self.teams["rec_clean"] = self._create_team("Rec clean", recording_domains=["clean.com"])
        self.teams["rec_null_field"] = self._create_team(
            "Null field", app_urls=["https://clean.com", None], recording_domains=None
        )

    def _create_team(self, name, app_urls=None, recording_domains=None):
        """Utility to create teams with default values"""
        return self.Team.objects.create(
            organization=self.organization,
            project=self.project,
            name=name,
            app_urls=app_urls if app_urls is not None else [],
            recording_domains=recording_domains,
        )

    @parameterized.expand(
        [
            ("app_mixed", ["https://valid.com", "https://valid2.com"]),
            ("app_all_nulls", []),
            ("app_empty", []),
            ("app_clean", ["https://clean.com"]),
        ]
    )
    def test_app_urls_null_removal(self, team_key, expected_app_urls):
        """Test that nulls are correctly removed from app_urls arrays"""
        team = self.teams[team_key]
        team.refresh_from_db()

        self.assertEqual(team.app_urls, expected_app_urls)

    @parameterized.expand(
        [
            ("rec_mixed", ["domain1.com", "domain2.com"]),
            ("rec_all_nulls", []),
            ("rec_empty", []),
            ("rec_clean", ["clean.com"]),
            ("rec_null_field", None),
        ]
    )
    def test_recording_domains_null_removal(self, team_key, expected_recording_domains):
        """Test that nulls are correctly removed from recording_domains arrays"""
        team = self.teams[team_key]
        team.refresh_from_db()

        self.assertEqual(team.recording_domains, expected_recording_domains)
