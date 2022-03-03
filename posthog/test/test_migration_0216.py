from django.db import IntegrityError

from posthog.test.base import NonAtomicTestMigrations


class TaggedItemsUniquenessTest(NonAtomicTestMigrations):

    migrate_from = "0215_add_tags_back"  # type: ignore
    migrate_to = "0216_uniqueness_constraint_tagged_items"  # type: ignore

    def setUpBeforeMigration(self, apps):
        Dashboard = apps.get_model("posthog", "Dashboard")
        Tag = apps.get_model("posthog", "Tag")
        TaggedItem = apps.get_model("posthog", "TaggedItem")

        # Setup
        self.tag = Tag.objects.create(name="tag", team_id=self.team.id)
        self.dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")

        # Before migration you can create duplicate tagged items
        taggeditem_1 = TaggedItem.objects.create(dashboard_id=self.dashboard.id, tag_id=self.tag.id)
        taggeditem_2 = TaggedItem.objects.create(dashboard_id=self.dashboard.id, tag_id=self.tag.id)
        self.assertNotEqual(taggeditem_1.id, taggeditem_2.id)

        # Remove duplicate row so that unique index can be created
        taggeditem_2.delete()

    def test_taggeditems_uniqueness(self):
        TaggedItem = self.apps.get_model("posthog", "TaggedItem")  # type: ignore

        with self.assertRaises(IntegrityError):
            TaggedItem.objects.create(dashboard_id=self.dashboard.id, tag_id=self.tag.id)

    def tearDown(self):
        Dashboard = self.apps.get_model("posthog", "Dashboard")  # type: ignore
        Dashboard.objects.filter(id=self.dashboard.id).delete()
