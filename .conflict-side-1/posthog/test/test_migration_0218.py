import pytest
from posthog.test.base import NonAtomicTestMigrations

from django.db import IntegrityError

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class TaggedItemsUniquenessTest(NonAtomicTestMigrations):
    migrate_from = "0217_team_primary_dashboard"
    migrate_to = "0218_uniqueness_constraint_tagged_items"

    def setUpBeforeMigration(self, apps):
        Dashboard = apps.get_model("posthog", "Dashboard")
        Insight = apps.get_model("posthog", "Insight")
        Tag = apps.get_model("posthog", "Tag")
        TaggedItem = apps.get_model("posthog", "TaggedItem")

        # Setup
        self.tag = Tag.objects.create(name="tag", team_id=self.team.id)
        self.dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        self.insight = Insight.objects.create(team_id=self.team.id, name="XYZ", dashboard=self.dashboard)

        # Before migration you can create duplicate tagged items
        taggeditem_1 = TaggedItem.objects.create(dashboard_id=self.dashboard.id, tag_id=self.tag.id)
        taggeditem_2 = TaggedItem.objects.create(dashboard_id=self.dashboard.id, tag_id=self.tag.id)
        self.assertNotEqual(taggeditem_1.id, taggeditem_2.id)

        # More duplicate tagged items to ensure deduping works properly
        TaggedItem.objects.create(insight_id=self.insight.id, tag_id=self.tag.id)
        TaggedItem.objects.create(insight_id=self.insight.id, tag_id=self.tag.id)

    def test_taggeditems_uniqueness(self):
        TaggedItem = self.apps.get_model("posthog", "TaggedItem")  # type: ignore

        self.assertEqual(TaggedItem.objects.all().count(), 2)

        with self.assertRaises(IntegrityError):
            TaggedItem.objects.create(dashboard_id=self.dashboard.id, tag_id=self.tag.id)

    def tearDown(self):
        Dashboard = self.apps.get_model("posthog", "Dashboard")  # type: ignore
        Dashboard.objects.filter(id=self.dashboard.id).delete()
        super().tearDown()
