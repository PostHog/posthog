from django.db import transaction
from django.db.models import Q

from posthog.models import Tag as TagModel
from posthog.models import TaggedItem as TaggedItemModel
from posthog.models import Team
from posthog.test.base import TestMigrations


class TagsTestCase(TestMigrations):
    migrate_from = "0011_add_tags_back"  # type: ignore
    migrate_to = "0012_migrate_tags_v2"  # type: ignore
    assert_snapshots = True

    @property
    def app(self):
        return "ee"

    def setUpBeforeMigration(self, apps):
        EnterpriseEventDefinition = apps.get_model("ee", "EnterpriseEventDefinition")
        EnterprisePropertyDefinition = apps.get_model("ee", "EnterprisePropertyDefinition")

        # Setup
        # apps.get_model("posthog", "Tag") doesn't work in setup because of a dependency issue
        tag = TagModel.objects.create(name="existing tag", team_id=self.team.id)
        self.event_definition = EnterpriseEventDefinition.objects.create(
            team_id=self.team.id,
            name="enterprise event",
            deprecated_tags=["a", "b", "c", "a", "b", "existing tag", "", "  ", None],
        )
        self.property_definition_with_tags = EnterprisePropertyDefinition.objects.create(
            team_id=self.team.id, name="property def with tags", deprecated_tags=["c", "d", "d", "existing tag"],
        )
        self.property_definition_without_tags = EnterprisePropertyDefinition.objects.create(
            team_id=self.team.id, name="property def without tags",
        )
        TaggedItemModel.objects.create(tag=tag, property_definition_id=self.property_definition_with_tags.id)

        # Setup for batched tags
        self.team2 = Team.objects.create(
            organization=self.organization,
            api_token="token12345",
            test_account_filters=[
                {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"},
            ],
        )
        self.team2_total_property_definitions = 1_001
        tag2 = TagModel.objects.create(name="existing tag", team_id=self.team2.id)
        with transaction.atomic():
            for _tag in range(self.team2_total_property_definitions):
                EnterprisePropertyDefinition.objects.create(
                    name=f"batch_prop_{_tag}", team_id=self.team2.id, deprecated_tags=[_tag, "existing tag"],
                )
        TaggedItemModel.objects.create(
            tag=tag2,
            property_definition_id=EnterprisePropertyDefinition.objects.filter(team_id=self.team2.id).first().id,
        )

    def test_tags_migrated(self):
        Tag = self.apps.get_model("posthog", "Tag")  # type: ignore
        TaggedItem = self.apps.get_model("posthog", "TaggedItem")  # type: ignore
        EnterpriseEventDefinition = self.apps.get_model("ee", "EnterpriseEventDefinition")  # type: ignore
        EnterprisePropertyDefinition = self.apps.get_model("ee", "EnterprisePropertyDefinition")  # type: ignore

        event_definition = EnterpriseEventDefinition.objects.get(id=self.event_definition.id)
        self.assertEqual(
            list(event_definition.tagged_items.order_by("tag__name").values_list("tag__name", flat=True)),
            ["a", "b", "c", "existing tag"],
        )

        property_definition_with_tags = EnterprisePropertyDefinition.objects.get(
            id=self.property_definition_with_tags.id
        )
        self.assertEqual(
            list(property_definition_with_tags.tagged_items.order_by("tag__name").values_list("tag__name", flat=True)),
            ["c", "d", "existing tag"],
        )

        property_definition_without_tags = EnterprisePropertyDefinition.objects.get(
            id=self.property_definition_without_tags.id
        )
        self.assertEqual(property_definition_without_tags.tagged_items.count(), 0)

        self.assertEqual(
            sorted(Tag.objects.filter(team_id=self.team.id).all().values_list("name", flat=True)),
            ["a", "b", "c", "d", "existing tag"],
        )

        # By the end of the migration, the total count for team 2 should be
        # Tags = team2_total_property_definitions + 2 + team1_tags
        # TaggedItems = team2_total_property_definitions * 2 + team1_taggeditems
        self.assertEqual(Tag.objects.all().count(), self.team2_total_property_definitions + 1 + 5)
        self.assertEqual(TaggedItem.objects.all().count(), self.team2_total_property_definitions * 2 + 7)

    def tearDown(self):
        EnterpriseEventDefinition = self.apps.get_model("ee", "EnterpriseEventDefinition")  # type: ignore
        EnterprisePropertyDefinition = self.apps.get_model("ee", "EnterprisePropertyDefinition")  # type: ignore

        EnterprisePropertyDefinition.objects.filter(
            Q(id__in=[self.property_definition_with_tags.id, self.property_definition_without_tags.id])
            | Q(name__startswith="batch_prop_")
        ).delete()
        EnterpriseEventDefinition.objects.filter(id=self.event_definition.id).delete()
        Team.objects.get(id=self.team2.id).delete()
        super().tearDown()
