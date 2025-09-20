import pytest
from posthog.test.base import TestMigrations

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class RecordingDomainMigrationTestCase(TestMigrations):
    migrate_from = "0258_team_recording_domains"
    migrate_to = "0259_backfill_team_recording_domains"
    assert_snapshots = True

    def setUpBeforeMigration(self, apps):
        Organization = apps.get_model("posthog", "Organization")
        Team = apps.get_model("posthog", "Team")

        org = Organization.objects.create(name="o1")

        # CASE 1:
        # Team with empty app_urls
        Team.objects.create(name="t1", organization=org, app_urls=[])

        # CASE 2:
        # Team with normal app_urls
        Team.objects.create(
            name="t2",
            organization=org,
            app_urls=[
                "https://example.com",
                "https://www.example2.com/test/test",
                "https://www.example2.com/test",
                "http://localhost:8000",
                "http://localhost:9000/test/test",
            ],
        )

        # CASE 3:
        # Team with wildcarded app_urls
        Team.objects.create(
            name="t3",
            organization=org,
            app_urls=["https://*.example.com", "https://*.app.example.com/test/test"],
        )

        # CASE 4:
        # Team with invalid urls in app_urls
        Team.objects.create(
            name="t4",
            organization=org,
            app_urls=[
                "jamaican me crazy",
                "test.com",
                "http://",
                "",
                "https://test.example.com",
            ],
        )

    def test_backfill_recording_domain(self):
        Team = self.apps.get_model("posthog", "Team")  # type: ignore

        # CASE 1:
        self.assertEqual(set(Team.objects.get(name="t1").recording_domains), set())

        # CASE 2:
        self.assertEqual(
            set(Team.objects.get(name="t2").recording_domains),
            {
                "https://example.com",
                "https://www.example2.com",
                "http://localhost:8000",
                "http://localhost:9000",
            },
        )

        # CASE 3:
        self.assertEqual(
            set(Team.objects.get(name="t3").recording_domains),
            {"https://*.example.com", "https://*.app.example.com"},
        )

        # CASE 4:
        self.assertEqual(
            set(Team.objects.get(name="t4").recording_domains),
            {"https://test.example.com"},
        )

    def tearDown(self):
        Team = self.apps.get_model("posthog", "Team")  # type: ignore
        Team.objects.all().delete()
        super().tearDown()
