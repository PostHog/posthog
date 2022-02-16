from posthog.test.base import TestMigrations


class TagsTestCase(TestMigrations):

    migrate_from = "0212_deprecated_old_tags"  # type: ignore
    migrate_to = "0213_migrate_dashboard_insight_tags"  # type: ignore

    def setUpBeforeMigration(self, apps):
        Dashboard = apps.get_model("posthog", "Dashboard")
        Insight = apps.get_model("posthog", "Insight")

        self.dashboard = Dashboard.objects.create(
            team_id=self.team.id, name="private dashboard", deprecated_tags=["a", "b", "c", "a", "b"]
        )
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }
        self.insight_with_tags = Insight.objects.create(
            dashboard=self.dashboard, filters=filter_dict, team_id=self.team.id, deprecated_tags=["c", "d", "d"]
        )
        self.insight_without_tags = Insight.objects.create(
            dashboard=self.dashboard, filters=filter_dict, team_id=self.team.id
        )

    def test_tags_migrated(self):
        Tag = self.apps.get_model("posthog", "Tag")  # type: ignore
        TaggedItem = self.apps.get_model("posthog", "TaggedItem")  # type: ignore
        Dashboard = self.apps.get_model("posthog", "Dashboard")  # type: ignore
        Insight = self.apps.get_model("posthog", "Insight")  # type: ignore

        dashboard = Dashboard.objects.get(id=self.dashboard.id)
        self.assertEqual(dashboard.tagged_items.count(), 3)
        self.assertEqual(
            list(dashboard.tagged_items.order_by("tag__name").values_list("tag__name", flat=True)), ["a", "b", "c"]
        )

        insight_with_tags = Insight.objects.get(id=self.insight_with_tags.id)
        self.assertEqual(insight_with_tags.tagged_items.count(), 2)
        self.assertEqual(
            list(insight_with_tags.tagged_items.order_by("tag__name").values_list("tag__name", flat=True)), ["c", "d"]
        )

        insight_without_tags = Insight.objects.get(id=self.insight_without_tags.id)
        self.assertEqual(insight_without_tags.tagged_items.count(), 0)

        self.assertEqual(TaggedItem.objects.all().count(), 5)
        self.assertEqual(Tag.objects.all().count(), 4)

    def tearDown(self):
        Insight = self.apps.get_model("posthog", "Insight")  # type: ignore
        Insight.objects.filter(id__in=[self.insight_with_tags.id, self.insight_without_tags.id]).delete()
        Dashboard = self.apps.get_model("posthog", "Dashboard")  # type: ignore
        Dashboard.objects.filter(id=self.dashboard.id).delete()
