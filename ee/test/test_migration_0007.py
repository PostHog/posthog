from django.contrib.contenttypes.models import ContentType

from posthog.test.base import TestMigrations


class TagsTestCase(TestMigrations):

    migrate_from = "0006_event_definition_verification"  # type: ignore
    migrate_to = "0007_migrate_definitions_tags"  # type: ignore

    def setUpBeforeMigration(self, apps):
        EnterpriseEventDefinition = apps.get_model("ee", "EnterpriseEventDefinition")
        EnterprisePropertyDefinition = apps.get_model("ee", "EnterprisePropertyDefinition")

        self.event_definition = EnterpriseEventDefinition.objects.create(
            team_id=self.team.id, name="enterprise event", tags=["a", "b", "c"]
        ).id
        self.property_definition_with_tags = EnterprisePropertyDefinition.objects.create(
            team_id=self.team.id, name="property def with tags", tags=["b", "c", "d", "e"]
        ).id
        self.property_definition_without_tags = EnterprisePropertyDefinition.objects.create(
            team_id=self.team.id, name="property def without tags",
        ).id

    def test_tags_migrated(self):
        EnterpriseTaggedItem = self.apps.get_model("posthog", "EnterpriseTaggedItem")  # type: ignore
        EnterpriseEventDefinition = self.apps.get_model("ee", "EnterpriseEventDefinition")  # type: ignore
        EnterprisePropertyDefinition = self.apps.get_model("ee", "EnterprisePropertyDefinition")  # type: ignore
        event_definition_type = ContentType.objects.get_for_model(EnterpriseEventDefinition)
        property_definition_type = ContentType.objects.get_for_model(EnterprisePropertyDefinition)

        event_definition_tags = EnterpriseTaggedItem.objects.filter(
            content_type__pk=event_definition_type.id, object_id=self.event_definition
        )
        self.assertEqual(event_definition_tags.count(), 3)
        self.assertEqual(list(event_definition_tags.values_list("tag", flat=True)), ["a", "b", "c"])

        property_definition_with_tags_tags = EnterpriseTaggedItem.objects.filter(
            content_type__pk=property_definition_type.id, object_id=self.property_definition_with_tags
        )
        self.assertEqual(property_definition_with_tags_tags.count(), 4)
        self.assertEqual(list(property_definition_with_tags_tags.values_list("tag", flat=True)), ["b", "c", "d", "e"])

        property_definition_without_tags_tags = EnterpriseTaggedItem.objects.filter(
            content_type__pk=property_definition_type.id, object_id=self.property_definition_without_tags
        )
        self.assertEqual(property_definition_without_tags_tags.count(), 0)

        self.assertEqual(EnterpriseTaggedItem.objects.all().count(), 7)
        self.assertEqual(EnterpriseTaggedItem.objects.order_by("tag").values("tag").distinct().count(), 5)

    def tearDown(self):
        EnterpriseEventDefinition = self.apps.get_model("ee", "EnterpriseEventDefinition")  # type: ignore
        EnterpriseEventDefinition.objects.filter(id=self.event_definition).delete()
        EnterprisePropertyDefinition = self.apps.get_model("ee", "EnterprisePropertyDefinition")  # type: ignore
        EnterprisePropertyDefinition.objects.filter(
            id__in=[self.property_definition_with_tags, self.property_definition_without_tags]
        ).delete()
