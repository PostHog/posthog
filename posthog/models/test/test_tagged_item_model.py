from posthog.test.base import BaseTest

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from parameterized import parameterized

from posthog.models import Tag, TaggedItem, Team
from posthog.models.tagged_items_relation import Taggable

from products.actions.backend.models.action import Action
from products.dashboards.backend.models.dashboard import Dashboard
from products.event_definitions.backend.models import EventDefinition
from products.product_analytics.backend.facade.models import Insight


class TestTaggedItem(BaseTest):
    def _taggable(self, kind: str) -> Taggable:
        if kind == "dashboard":
            return Dashboard.objects.create(team_id=self.team.id, name="dashboard")
        if kind == "insight":
            return Insight.objects.create(filters={"events": [{"id": "$pageview"}]}, team_id=self.team.id)
        if kind == "event_definition":
            return EventDefinition.objects.create(team=self.team, name="event")
        return Action.objects.create(team=self.team, name="action")

    def test_exactly_one_object_constraint(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        event_definition = EventDefinition.objects.create(team=self.team, name="event")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        with self.assertRaises(ValidationError):
            TaggedItem.objects.create(
                tag_id=tag.id,
                content_type=ContentType.objects.get_for_model(Dashboard),
                object_id=dashboard.id,
                object_uuid=event_definition.id,
            )

    def test_at_least_one_constraint(self):
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        with self.assertRaises(ValidationError):
            TaggedItem.objects.create(tag_id=tag.id)

    def test_content_type_is_required(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        with self.assertRaises(ValidationError):
            TaggedItem.objects.create(tag_id=tag.id, object_id=dashboard.id)

    def test_unregistered_content_type_is_rejected(self):
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        with self.assertRaises(ValidationError):
            TaggedItem.objects.create(
                tag_id=tag.id, content_type=ContentType.objects.get_for_model(Team), object_id=self.team.id
            )

    def test_object_column_must_match_the_content_type(self):
        """A row filed under the wrong typed column reads back as no object at all."""
        event_definition = EventDefinition.objects.create(team=self.team, name="event")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        with self.assertRaises(ValidationError):
            TaggedItem.objects.create(
                tag_id=tag.id,
                content_type=ContentType.objects.get_for_model(EventDefinition),
                object_id=self.team.id,
            )
        assert event_definition.tagged_items.count() == 0

    @parameterized.expand(["dashboard", "insight", "event_definition", "action"])
    def test_uniqueness_constraint(self, kind: str):
        tag = Tag.objects.create(name="tag", team_id=self.team.id)
        obj = self._taggable(kind)

        obj.tagged_items.create(tag=tag)
        with self.assertRaises(ValidationError):
            obj.tagged_items.create(tag=tag)

    def test_uniqueness_constraint_property_definition(self):
        try:
            from ee.models import EnterprisePropertyDefinition
        except ImportError:
            self.skipTest("needs the ee app")

        property_definition = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        property_definition.tagged_items.create(tag=tag)
        with self.assertRaises(ValidationError):
            property_definition.tagged_items.create(tag=tag)


class TestTaggedItemGenericColumns(BaseTest):
    """The pointer columns name the tagged object, and the team follows the tag."""

    def test_integer_keyed_object_fills_object_id(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dashboard")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        tagged_item = dashboard.tagged_items.create(tag=tag)

        tagged_item.refresh_from_db()
        assert tagged_item.object_id == dashboard.id
        assert tagged_item.object_uuid is None
        assert tagged_item.content_type == ContentType.objects.get_for_model(Dashboard)
        assert tagged_item.team_id == tag.team_id

    def test_uuid_keyed_object_fills_object_uuid(self):
        event_definition = EventDefinition.objects.create(team=self.team, name="event")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        tagged_item = event_definition.tagged_items.create(tag=tag)

        tagged_item.refresh_from_db()
        assert tagged_item.object_uuid == event_definition.id
        assert tagged_item.object_id is None
        assert tagged_item.content_type == ContentType.objects.get_for_model(EventDefinition)
        assert tagged_item.team_id == tag.team_id

    def test_enterprise_definition_stores_the_base_content_type(self):
        """An enterprise definition must not create a second content type for its tags."""
        try:
            from ee.models import EnterpriseEventDefinition
        except ImportError:
            self.skipTest("needs the ee app")

        event_definition = EnterpriseEventDefinition.objects.create(team=self.team, name="enterprise event")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        tagged_item = event_definition.tagged_items.create(tag=tag)

        tagged_item.refresh_from_db()
        assert tagged_item.content_type == ContentType.objects.get_for_model(EventDefinition)
        assert tagged_item.content_type != ContentType.objects.get_for_model(EnterpriseEventDefinition)
        assert tagged_item.object_uuid == event_definition.id

    def test_bulk_create_fills_the_team(self):
        """bulk_create never calls save(), and the Zendesk import writes ticket tags through it."""
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dashboard")
        event_definition = EventDefinition.objects.create(team=self.team, name="event")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        TaggedItem.objects.bulk_create(
            [
                TaggedItem.for_content_object(tag, dashboard),
                TaggedItem.for_content_object(tag, event_definition),
            ]
        )

        by_type = {item.related_object_type: item for item in TaggedItem.objects.filter(tag=tag)}
        assert by_type["dashboard"].object_id == dashboard.id
        assert by_type["dashboard"].content_type == ContentType.objects.get_for_model(Dashboard)
        assert by_type["event_definition"].object_uuid == event_definition.id
        assert by_type["event_definition"].content_type == ContentType.objects.get_for_model(EventDefinition)
        assert all(item.team_id == tag.team_id for item in by_type.values())

    def test_bulk_create_loads_uncached_tags_once(self):
        dashboards = [Dashboard.objects.create(team_id=self.team.id, name=f"dashboard {i}") for i in range(3)]
        tag = Tag.objects.create(name="tag", team_id=self.team.id)
        content_type = ContentType.objects.get_for_model(Dashboard)
        rows = [
            TaggedItem(tag_id=tag.id, content_type=content_type, object_id=dashboard.id) for dashboard in dashboards
        ]

        with self.assertNumQueries(2):
            TaggedItem.objects.bulk_create(rows)

        assert all(row.team_id == tag.team_id for row in rows)

    def test_save_with_update_fields_persists_the_team(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dashboard")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)
        other_team = Team.objects.create(organization=self.organization, name="other")
        tagged_item = dashboard.tagged_items.create(tag=tag)
        TaggedItem.objects.filter(pk=tagged_item.pk).update(team_id=other_team.id)

        tagged_item = TaggedItem.objects.get(pk=tagged_item.pk)
        tagged_item.save(update_fields=["tag"])

        tagged_item.refresh_from_db()
        assert tagged_item.team_id == tag.team_id

    def test_team_follows_the_tag(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dashboard")
        other_team = Team.objects.create(organization=self.organization, name="other")
        tagged_item = dashboard.tagged_items.create(tag=Tag.objects.create(name="tag", team_id=self.team.id))

        tagged_item.tag = Tag.objects.create(name="tag", team_id=other_team.id)
        tagged_item.sync_team()

        assert tagged_item.team_id == other_team.id

    def test_helpers_report_the_tagged_object(self):
        insight = Insight.objects.create(filters={"events": [{"id": "$pageview"}]}, team_id=self.team.id)
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        tagged_item = insight.tagged_items.create(tag=tag)

        assert tagged_item.related_object_type == "insight"
        assert tagged_item.content_object == insight

    def test_queryset_helpers_select_by_object(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dashboard")
        other_dashboard = Dashboard.objects.create(team_id=self.team.id, name="other dashboard")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)
        tagged_item = dashboard.tagged_items.create(tag=tag)
        other_dashboard.tagged_items.create(tag=tag)

        assert list(TaggedItem.objects.for_object(dashboard)) == [tagged_item]
        assert TaggedItem.objects.for_model(Dashboard).count() == 2
        assert list(TaggedItem.objects.for_objects(Dashboard, [dashboard.id])) == [tagged_item]


class TestTaggedItemsRelation(BaseTest):
    def test_reverse_accessor_writes_the_pointer(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dashboard")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        tagged_item, _ = dashboard.tagged_items.get_or_create(tag=tag)

        tagged_item.refresh_from_db()
        assert tagged_item.object_id == dashboard.id
        assert tagged_item.content_type == ContentType.objects.get_for_model(Dashboard)
        assert tagged_item.team_id == tag.team_id
        assert list(dashboard.tagged_items.all()) == [tagged_item]

    @parameterized.expand([("add",), ("set",)])
    def test_moving_a_row_through_the_relation_is_refused(self, method: str):
        source = Dashboard.objects.create(team_id=self.team.id, name="source")
        target = Dashboard.objects.create(team_id=self.team.id, name="target")
        item = source.tagged_items.create(tag=Tag.objects.create(name="tag", team_id=self.team.id))

        with self.assertRaises(NotImplementedError):
            if method == "add":
                target.tagged_items.add(item)
            else:
                target.tagged_items.set([item])

        item.refresh_from_db()
        assert item.object_id == source.id

    @parameterized.expand([("integer key", "dashboard"), ("uuid key", "event_definition")])
    def test_filter_and_prefetch_through_the_relation(self, _name: str, kind: str):
        model: type[models.Model]
        tagged: models.Model
        untagged: models.Model
        if kind == "dashboard":
            model = Dashboard
            tagged = Dashboard.objects.create(team_id=self.team.id, name="tagged")
            untagged = Dashboard.objects.create(team_id=self.team.id, name="untagged")
        else:
            model = EventDefinition
            tagged = EventDefinition.objects.create(team=self.team, name="tagged")
            untagged = EventDefinition.objects.create(team=self.team, name="untagged")
        tagged.tagged_items.create(tag=Tag.objects.create(name="wanted", team_id=self.team.id))

        assert list(model.objects.filter(tagged_items__tag__name="wanted")) == [tagged]

        by_pk = {
            obj.pk: obj
            for obj in model.objects.filter(pk__in=[tagged.pk, untagged.pk]).prefetch_related("tagged_items__tag")
        }
        assert [item.tag.name for item in by_pk[tagged.pk].tagged_items.all()] == ["wanted"]
        assert list(by_pk[untagged.pk].tagged_items.all()) == []

    def test_enterprise_and_base_definitions_share_their_tags(self):
        try:
            from ee.models import EnterpriseEventDefinition
        except ImportError:
            self.skipTest("needs the ee app")

        enterprise_definition = EnterpriseEventDefinition.objects.create(team=self.team, name="event")
        base_definition = EventDefinition.objects.get(pk=enterprise_definition.pk)
        tag = Tag.objects.create(name="shared", team_id=self.team.id)

        tagged_item = enterprise_definition.tagged_items.create(tag=tag)

        assert tagged_item.content_type == ContentType.objects.get_for_model(EventDefinition)
        assert list(base_definition.tagged_items.all()) == [tagged_item]
        assert list(EnterpriseEventDefinition.objects.filter(tagged_items__tag__name="shared")) == [
            enterprise_definition
        ]
        prefetched = EnterpriseEventDefinition.objects.prefetch_related("tagged_items").get(pk=enterprise_definition.pk)
        assert list(prefetched.tagged_items.all()) == [tagged_item]

    def test_deleting_the_object_deletes_its_tagged_items(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dashboard")
        dashboard.tagged_items.create(tag=Tag.objects.create(name="tag", team_id=self.team.id))

        dashboard.delete()

        assert not TaggedItem.objects.for_model(Dashboard).exists()

    def test_bulk_create_from_content_objects_fills_the_pointer(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dashboard")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        TaggedItem.objects.bulk_create([TaggedItem.for_content_object(tag, dashboard)])

        tagged_item = TaggedItem.objects.for_object(dashboard).get()
        assert tagged_item.object_id == dashboard.id
        assert tagged_item.related_object_type == "dashboard"
        assert tagged_item.content_object == dashboard
