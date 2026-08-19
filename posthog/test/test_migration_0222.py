import pytest
from posthog.test.base import TestMigrations

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class DeletedPrimaryDashboardTestCase(TestMigrations):
    migrate_from = "0221_add_activity_log_model"
    migrate_to = "0222_fix_deleted_primary_dashboards"
    assert_snapshots = True

    def setUpBeforeMigration(self, apps):
        Organization = apps.get_model("posthog", "Organization")
        Dashboard = apps.get_model("posthog", "Dashboard")
        Team = apps.get_model("posthog", "Team")

        org = Organization.objects.create(name="o1")

        # CASE 1:
        # Team with an existing primary dashboard that's not deleted isn't affected
        # Expect: t1.primary_dashboard = d1
        team_1 = Team.objects.create(name="t1", organization=org)
        dashboard_1 = Dashboard.objects.create(name="d1", team=team_1)
        team_1.primary_dashboard = dashboard_1
        team_1.save()

        # CASE 2:
        # Team with a deleted primary dashboard and no other dashboards is set to None
        # Expect: t2.primary_dashboard = None
        team_2 = Team.objects.create(name="t2", organization=org)
        dashboard_2 = Dashboard.objects.create(name="d2", team=team_2, deleted=True)
        team_2.primary_dashboard = dashboard_2
        team_2.save()

        # CASE 3:
        # Team with a deleted primary dashboard and other dashboards is set to the first dashboard
        # Expect: t3.primary_dashboard = d4
        team_3 = Team.objects.create(name="t3", organization=org)
        dashboard_3 = Dashboard.objects.create(name="d3", team=team_3, deleted=True)
        team_3.primary_dashboard = dashboard_3
        team_3.save()
        Dashboard.objects.create(name="d4", team=team_3)

        # CASE 4:
        # Team with no primary dashboards is set to the first non deleted dashboard
        # Expect: t4.primary_dashboard = d6 (even though d5 is created first)
        team_4 = Team.objects.create(name="t4", organization=org)
        Dashboard.objects.create(name="d5", team=team_4, deleted=True)
        Dashboard.objects.create(name="d6", team=team_4)

        # CASE 5:
        # Team with a deleted primary dashboard is set to the first non-deleted dashboard
        # Expect: t5.primary_dashboard = d9
        team_5 = Team.objects.create(name="t5", organization=org)
        dashboard_7 = Dashboard.objects.create(name="d7", team=team_5, deleted=True)
        team_5.primary_dashboard = dashboard_7
        team_5.save()
        Dashboard.objects.create(name="d8", team=team_5, deleted=True)
        Dashboard.objects.create(name="d9", team=team_5)

    def test_backfill_primary_dashboard(self):
        Dashboard = self.apps.get_model("posthog", "Dashboard")  # type: ignore
        Team = self.apps.get_model("posthog", "Team")  # type: ignore

        # CASE 1:
        self.assertEqual(
            Team.objects.get(name="t1").primary_dashboard.id,
            Dashboard.objects.get(name="d1").id,
        )

        # CASE 2:
        self.assertEqual(Team.objects.get(name="t2").primary_dashboard, None)

        # CASE 3:
        self.assertEqual(
            Team.objects.get(name="t3").primary_dashboard.id,
            Dashboard.objects.get(name="d4").id,
        )

        # CASE 4:
        self.assertEqual(
            Team.objects.get(name="t4").primary_dashboard.id,
            Dashboard.objects.get(name="d6").id,
        )

        # CASE 5:
        self.assertEqual(
            Team.objects.get(name="t5").primary_dashboard.id,
            Dashboard.objects.get(name="d9").id,
        )

    def tearDown(self):
        Team = self.apps.get_model("posthog", "Team")  # type: ignore
        Dashboard = self.apps.get_model("posthog", "Dashboard")  # type: ignore
        Dashboard.objects.all().delete()
        Team.objects.all().delete()
        super().tearDown()
