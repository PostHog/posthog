from django.contrib.contenttypes.models import ContentType

from posthog.test.base import TestMigrations


class TagsTestCase(TestMigrations):

    migrate_from = "0201_global_tags_setup"  # type: ignore
    migrate_to = "0202_migrate_dashboard_insight_tags"  # type: ignore

    def setUpBeforeMigration(self, apps):
        Dashboard = apps.get_model("posthog", "Dashboard")
        Insight = apps.get_model("posthog", "Insight")

        self.dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard", tags=["a", "b", "c"])
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }
        self.insight_with_tags = Insight.objects.create(
            dashboard=self.dashboard, filters=filter_dict, team_id=self.team.id, tags=["c", "d"]
        )
        self.insight_without_tags = Insight.objects.create(
            dashboard=self.dashboard, filters=filter_dict, team_id=self.team.id
        )

    def test_tags_migrated(self):
        EnterpriseTaggedItem = self.apps.get_model("posthog", "EnterpriseTaggedItem")  # type: ignore
        Dashboard = self.apps.get_model("posthog", "Dashboard")  # type: ignore
        Insight = self.apps.get_model("posthog", "Insight")  # type: ignore
        dashboard_type = ContentType.objects.get_for_model(Dashboard)
        insight_type = ContentType.objects.get_for_model(Insight)

        dashboard_tags = EnterpriseTaggedItem.objects.filter(
            content_type__pk=dashboard_type.id, object_id=self.dashboard.id
        )
        self.assertEqual(dashboard_tags.count(), 3)
        self.assertEqual(list(dashboard_tags.order_by("tag").values_list("tag", flat=True)), ["a", "b", "c"])

        insight_with_tags_tags = EnterpriseTaggedItem.objects.filter(
            content_type__pk=insight_type.id, object_id=self.insight_with_tags.id
        )
        self.assertEqual(insight_with_tags_tags.count(), 2)
        self.assertEqual(list(insight_with_tags_tags.values_list("tag", flat=True)), ["c", "d"])

        insight_without_tags_tags = EnterpriseTaggedItem.objects.filter(
            content_type__pk=insight_type.id, object_id=self.insight_without_tags.id
        )
        self.assertEqual(insight_without_tags_tags.count(), 0)

        self.assertEqual(EnterpriseTaggedItem.objects.all().count(), 5)
        self.assertEqual(EnterpriseTaggedItem.objects.order_by("tag").values("tag").distinct().count(), 4)

    def tearDown(self):
        Insight = self.apps.get_model("posthog", "Insight")  # type: ignore
        Insight.objects.filter(id__in=[self.insight_with_tags.id, self.insight_without_tags.id]).delete()
        Dashboard = self.apps.get_model("posthog", "Dashboard")  # type: ignore
        Dashboard.objects.filter(id=self.dashboard.id).delete()
