from posthog.test.base import TestMigrations


class TagsTestCase(TestMigrations):

    migrate_from = "0221_add_activity_log_model"  # type: ignore
    migrate_to = "0222_fix_deleted_primary_dashboards"  # type: ignore
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

        # CASE 3:
        # Team with no primary dashboards is set to the first non deleted dashboard
        # Expect: t4.primary_dashboard = d6 (even though d3 is created first)
        team_4 = Team.objects.create(name="t4", organization=org)
        Dashboard.objects.create(name="d5", team=team_4, deleted=True)
        Dashboard.objects.create(name="d6", team=team_4)

    def test_backfill_primary_dashboard(self):
        Dashboard = self.apps.get_model("posthog", "Dashboard")  # type: ignore
        Team = self.apps.get_model("posthog", "Team")  # type: ignore

        # CASE 1:
        self.assertEqual(Team.objects.get(name="t1").primary_dashboard.id, Dashboard.objects.get(name="d1").id)

        # CASE 2:
        self.assertEqual(Team.objects.get(name="t2").primary_dashboard, None)

        # CASE 3:
        self.assertEqual(Team.objects.get(name="t3").primary_dashboard.id, Dashboard.objects.get(name="d4").id)

        # CASE 4:
        self.assertEqual(Team.objects.get(name="t4").primary_dashboard.id, Dashboard.objects.get(name="d6").id)

    def tearDown(self):
        Team = self.apps.get_model("posthog", "Team")  # type: ignore
        Dashboard = self.apps.get_model("posthog", "Dashboard")  # type: ignore
        Dashboard.objects.all().delete()
        Team.objects.all().delete()
