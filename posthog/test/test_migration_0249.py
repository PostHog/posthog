from posthog.test.base import TestMigrations


class FixingDashboardTilesTestCase(TestMigrations):

    migrate_from = "0248_add_context_for_csv_exports"  # type: ignore
    migrate_to = "0249_add_sharingconfiguration"  # type: ignore

    def setUpBeforeMigration(self, apps):
        Organization = apps.get_model("posthog", "Organization")
        Dashboard = apps.get_model("posthog", "Dashboard")
        Team = apps.get_model("posthog", "Team")

        org = Organization.objects.create(name="o1")
        team = Team.objects.create(name="t1", organization=org)

        dashboards = [
            Dashboard(team=team, name=f"d{i}", share_token=f"share-{i}", is_shared=False) for i in range(1000)
        ]
        shared_dashboards = dashboards + [
            Dashboard(team=team, name=f"d{i}", share_token=f"share-{i}", is_shared=True) for i in range(1000, 2000)
        ]

        Dashboard.objects.bulk_create(dashboards + shared_dashboards)

    def test_migrate_creates_sharing_configurations(self):
        Dashboards = self.apps.get_model("posthog", "Dashboard")  # type: ignore

        for d in (
            Dashboards.objects.prefetch_related("sharingconfiguration_set").filter(deprecated_is_shared=True).all()
        ):
            assert d.deprecated_is_shared
            assert d.sharingconfiguration_set.first().enabled
            assert d.sharingconfiguration_set.first().access_token == d.deprecated_share_token

        for d in (
            Dashboards.objects.prefetch_related("sharingconfiguration_set").filter(deprecated_is_shared=False).all()
        ):
            assert not d.deprecated_is_shared
            assert not d.sharingconfiguration_set.first()

    def tearDown(self):
        Team = self.apps.get_model("posthog", "Team")  # type: ignore
        Dashboard = self.apps.get_model("posthog", "Dashboard")  # type: ignore
        SharingConfiguration = self.apps.get_model("posthog", "SharingConfiguration")  # type: ignore

        SharingConfiguration.objects.all().delete()
        Dashboard.objects.all().delete()
        Team.objects.all().delete()
