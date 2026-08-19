import pytest
from posthog.test.base import TestMigrations

from django.db.models import Q

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class TagsTestCase(TestMigrations):
    migrate_from = "0218_uniqueness_constraint_tagged_items"
    migrate_to = "0219_migrate_tags_v2"
    assert_snapshots = True

    def setUpBeforeMigration(self, apps):
        Dashboard = apps.get_model("posthog", "Dashboard")
        Insight = apps.get_model("posthog", "Insight")
        Tag = apps.get_model("posthog", "Tag")
        TaggedItem = apps.get_model("posthog", "TaggedItem")
        Team = apps.get_model("posthog", "Team")
        Organization = apps.get_model("posthog", "Organization")

        # Setup
        tag = Tag.objects.create(name="existing tag", team_id=self.team.id)
        self.dashboard = Dashboard.objects.create(
            team_id=self.team.id,
            name="private dashboard",
            deprecated_tags=["a", "b", "c", "a", "b", "existing tag", "", "  ", None],
        )
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }
        self.insight_with_tags = Insight.objects.create(
            dashboard=self.dashboard,
            filters=filter_dict,
            team_id=self.team.id,
            deprecated_tags=["c", "d", "d", "existing tag"],
        )
        self.insight_without_tags = Insight.objects.create(
            dashboard=self.dashboard, filters=filter_dict, team_id=self.team.id
        )
        TaggedItem.objects.create(tag=tag, insight_id=self.insight_with_tags.id)

        # Setup for batched tags
        self.org2 = Organization.objects.create(name="o1")
        self.team2 = Team.objects.create(
            organization=self.org2,
            api_token="token12345",
            test_account_filters=[
                {
                    "key": "email",
                    "value": "@posthog.com",
                    "operator": "not_icontains",
                    "type": "person",
                }
            ],
        )
        self.team2_total_insights = 1_001
        tag2 = Tag.objects.create(name="existing tag", team_id=self.team2.id)
        self.dashboard2 = Dashboard.objects.create(team_id=self.team2.id, name="dashboard")
        Insight.objects.bulk_create(
            [
                Insight(
                    dashboard=self.dashboard2,
                    filters=filter_dict,
                    team_id=self.team2.id,
                    deprecated_tags=[_tag, "existing tag"],
                )
                for _tag in range(self.team2_total_insights)
            ],
            ignore_conflicts=True,
            batch_size=1000,
        )
        TaggedItem.objects.create(
            tag=tag2,
            insight_id=Insight.objects.filter(team_id=self.team2.id).first().id,
        )

    def test_tags_migrated(self):
        Tag = self.apps.get_model("posthog", "Tag")  # type: ignore
        TaggedItem = self.apps.get_model("posthog", "TaggedItem")  # type: ignore
        Dashboard = self.apps.get_model("posthog", "Dashboard")  # type: ignore
        Insight = self.apps.get_model("posthog", "Insight")  # type: ignore

        dashboard = Dashboard.objects.get(id=self.dashboard.id)
        self.assertEqual(
            list(dashboard.tagged_items.order_by("tag__name").values_list("tag__name", flat=True)),
            ["a", "b", "c", "existing tag"],
        )

        insight_with_tags = Insight.objects.get(id=self.insight_with_tags.id)
        self.assertEqual(
            list(insight_with_tags.tagged_items.order_by("tag__name").values_list("tag__name", flat=True)),
            ["c", "d", "existing tag"],
        )

        insight_without_tags = Insight.objects.get(id=self.insight_without_tags.id)
        self.assertEqual(insight_without_tags.tagged_items.count(), 0)

        self.assertEqual(
            sorted(Tag.objects.filter(team_id=self.team.id).all().values_list("name", flat=True)),
            ["a", "b", "c", "d", "existing tag"],
        )

        # By the end of the migration, the total count for team 2 should be
        # Tags = team2_total_insights + 2 + team1_tags
        # TaggedItems = team2_total_insights * 3 + team1_taggeditems
        self.assertEqual(Tag.objects.all().count(), self.team2_total_insights + 1 + 5)
        self.assertEqual(TaggedItem.objects.all().count(), self.team2_total_insights * 2 + 7)

    def tearDown(self):
        Insight = self.apps.get_model("posthog", "Insight")  # type: ignore
        Insight.objects.filter(
            Q(id__in=[self.insight_with_tags.id, self.insight_without_tags.id]) | Q(dashboard_id=self.dashboard2.id)
        ).delete()
        Dashboard = self.apps.get_model("posthog", "Dashboard")  # type: ignore
        Dashboard.objects.filter(id=self.dashboard.id).delete()
        Team = self.apps.get_model("posthog", "Team")  # type: ignore
        Team.objects.get(id=self.team2.id).delete()
        Organization = self.apps.get_model("posthog", "Organization")  # type: ignore
        Organization.objects.get(id=self.org2.id).delete()
        super().tearDown()
