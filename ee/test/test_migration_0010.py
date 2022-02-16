import pytest

from posthog.test.base import TestMigrations


@pytest.mark.ee
class TagsTestCase(TestMigrations):

    migrate_from = "0009_null_definition_descriptions"  # type: ignore
    migrate_to = "0010_migrate_definitions_tags"  # type: ignore

    @property
    def app(self):
        return "ee"

    def setUpBeforeMigration(self, apps):
        EnterpriseEventDefinition = apps.get_model("ee", "EnterpriseEventDefinition")
        EnterprisePropertyDefinition = apps.get_model("ee", "EnterprisePropertyDefinition")

        self.event_definition = EnterpriseEventDefinition.objects.create(
            team_id=self.team.id, name="enterprise event", deprecated_tags=["a", "b", "c", "a", "b"]
        )
        self.property_definition_with_tags = EnterprisePropertyDefinition.objects.create(
            team_id=self.team.id, name="property def with tags", deprecated_tags=["b", "c", "d", "e", "e"]
        )
        self.property_definition_without_tags = EnterprisePropertyDefinition.objects.create(
            team_id=self.team.id, name="property def without tags",
        )

    def test_tags_migrated(self):
        Tag = self.apps.get_model("posthog", "Tag")  # type: ignore
        TaggedItem = self.apps.get_model("posthog", "TaggedItem")  # type: ignore
        EnterpriseEventDefinition = self.apps.get_model("ee", "EnterpriseEventDefinition")  # type: ignore
        EnterprisePropertyDefinition = self.apps.get_model("ee", "EnterprisePropertyDefinition")  # type: ignore

        event_definition = EnterpriseEventDefinition.objects.get(id=self.event_definition.id)
        self.assertEqual(event_definition.tagged_items.count(), 3)
        self.assertEqual(
            list(event_definition.tagged_items.order_by("tag__name").values_list("tag__name", flat=True)),
            ["a", "b", "c"],
        )

        property_definition_with_tags = EnterprisePropertyDefinition.objects.get(
            id=self.property_definition_with_tags.id
        )
        self.assertEqual(property_definition_with_tags.tagged_items.count(), 4)
        self.assertEqual(
            list(property_definition_with_tags.tagged_items.order_by("tag__name").values_list("tag__name", flat=True)),
            ["b", "c", "d", "e"],
        )

        property_definition_without_tags = EnterprisePropertyDefinition.objects.get(
            id=self.property_definition_without_tags.id
        )
        self.assertEqual(property_definition_without_tags.tagged_items.count(), 0)

        self.assertEqual(TaggedItem.objects.all().count(), 7)
        self.assertEqual(Tag.objects.all().count(), 5)

    def tearDown(self):
        EnterpriseEventDefinition = self.apps.get_model("ee", "EnterpriseEventDefinition")  # type: ignore
        EnterpriseEventDefinition.objects.filter(id=self.event_definition.id).delete()
        EnterprisePropertyDefinition = self.apps.get_model("ee", "EnterprisePropertyDefinition")  # type: ignore
        EnterprisePropertyDefinition.objects.filter(
            id__in=[self.property_definition_with_tags.id, self.property_definition_without_tags.id]
        ).delete()
