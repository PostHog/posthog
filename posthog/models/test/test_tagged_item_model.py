from posthog.test.base import BaseTest

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from posthog.models import Tag, TaggedItem

from products.actions.backend.models.action import Action
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.event_definitions.backend.models import EventDefinition
from products.product_analytics.backend.facade.models import Insight


class TestTaggedItem(BaseTest):
    def test_exactly_one_object_constraint(self):
        # Setup
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        insight = Insight.objects.create(filters={"events": [{"id": "$pageview"}]}, team_id=self.team.id)
        DashboardTile.objects.create(insight=insight, dashboard=dashboard)
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        # Before migration you can create duplicate tagged items
        with self.assertRaises(ValidationError):
            TaggedItem.objects.create(dashboard_id=dashboard.id, insight_id=insight.id, tag_id=tag.id)

    def test_at_least_one_constraint(self):
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        with self.assertRaises(ValidationError):
            TaggedItem.objects.create(tag_id=tag.id)

    def test_uniqueness_constraint_dashboard(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        TaggedItem.objects.create(dashboard_id=dashboard.id, tag_id=tag.id)
        with self.assertRaises(ValidationError):
            TaggedItem.objects.create(dashboard_id=dashboard.id, tag_id=tag.id)

    def test_uniqueness_constraint_insight(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        insight = Insight.objects.create(filters={"events": [{"id": "$pageview"}]}, team_id=self.team.id)
        DashboardTile.objects.create(insight=insight, dashboard=dashboard)
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        TaggedItem.objects.create(insight_id=insight.id, tag_id=tag.id)
        with self.assertRaises(ValidationError):
            TaggedItem.objects.create(insight_id=insight.id, tag_id=tag.id)

    def test_uniqueness_constraint_event_definition(self):
        try:
            from ee.models import EnterpriseEventDefinition
        except ImportError:
            pass
        else:
            event_definition = EnterpriseEventDefinition.objects.create(
                team=self.team, name="enterprise event", owner=self.user
            )
            tag = Tag.objects.create(name="tag", team_id=self.team.id)

            TaggedItem.objects.create(event_definition_id=event_definition.id, tag_id=tag.id)
            with self.assertRaises(ValidationError):
                TaggedItem.objects.create(event_definition_id=event_definition.id, tag_id=tag.id)

    def test_uniqueness_constraint_property_definition(self):
        try:
            from ee.models import EnterprisePropertyDefinition
        except ImportError:
            pass
        else:
            property_definition = EnterprisePropertyDefinition.objects.create(
                team=self.team, name="enterprise property"
            )
            tag = Tag.objects.create(name="tag", team_id=self.team.id)

            TaggedItem.objects.create(property_definition_id=property_definition.id, tag_id=tag.id)
            with self.assertRaises(ValidationError):
                TaggedItem.objects.create(property_definition_id=property_definition.id, tag_id=tag.id)

    def test_uniqueness_constraint_action(self):
        action = Action.objects.create(team=self.team, name="enterprise property")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        TaggedItem.objects.create(action_id=action.id, tag_id=tag.id)
        with self.assertRaises(ValidationError):
            TaggedItem.objects.create(action_id=action.id, tag_id=tag.id)


class TestTaggedItemGenericColumns(BaseTest):
    """The generic pointer is filled from whichever per-model foreign key is set.

    Both shapes are written until the migration finishes, so these assert the new columns
    agree with the old ones rather than replace them.
    """

    def test_integer_keyed_object_fills_object_id(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dashboard")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        tagged_item = TaggedItem.objects.create(dashboard_id=dashboard.id, tag_id=tag.id)

        tagged_item.refresh_from_db()
        assert tagged_item.object_id == dashboard.id
        assert tagged_item.object_uuid is None
        assert tagged_item.content_type == ContentType.objects.get_for_model(Dashboard)
        assert tagged_item.team_id == tag.team_id

    def test_uuid_keyed_object_fills_object_uuid(self):
        event_definition = EventDefinition.objects.create(team=self.team, name="event")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        tagged_item = TaggedItem.objects.create(event_definition_id=event_definition.id, tag_id=tag.id)

        tagged_item.refresh_from_db()
        assert tagged_item.object_uuid == event_definition.id
        assert tagged_item.object_id is None
        assert tagged_item.content_type == ContentType.objects.get_for_model(EventDefinition)
        assert tagged_item.team_id == tag.team_id

    def test_enterprise_definition_stores_the_base_content_type(self):
        """An enterprise definition must not create a second content type for its tags."""
        from ee.models import EnterpriseEventDefinition

        event_definition = EnterpriseEventDefinition.objects.create(team=self.team, name="enterprise event")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        tagged_item = TaggedItem.objects.create(event_definition_id=event_definition.id, tag_id=tag.id)

        tagged_item.refresh_from_db()
        assert tagged_item.content_type == ContentType.objects.get_for_model(EventDefinition)
        assert tagged_item.content_type != ContentType.objects.get_for_model(EnterpriseEventDefinition)
        assert tagged_item.object_uuid == event_definition.id

    def test_bulk_create_fills_the_generic_columns(self):
        """bulk_create never calls save(), and the Zendesk import writes ticket tags through it."""
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dashboard")
        event_definition = EventDefinition.objects.create(team=self.team, name="event")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        TaggedItem.objects.bulk_create(
            [TaggedItem(tag=tag, dashboard=dashboard), TaggedItem(tag=tag, event_definition=event_definition)]
        )

        by_type = {item.related_object_type: item for item in TaggedItem.objects.filter(tag=tag)}
        assert by_type["dashboard"].object_id == dashboard.id
        assert by_type["dashboard"].content_type == ContentType.objects.get_for_model(Dashboard)
        assert by_type["event_definition"].object_uuid == event_definition.id
        assert by_type["event_definition"].content_type == ContentType.objects.get_for_model(EventDefinition)
        assert all(item.team_id == tag.team_id for item in by_type.values())

    def test_retargeting_a_row_clears_the_other_object_column(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dashboard")
        event_definition = EventDefinition.objects.create(team=self.team, name="event")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)
        tagged_item = TaggedItem.objects.create(dashboard_id=dashboard.id, tag_id=tag.id)

        tagged_item.dashboard = None
        tagged_item.event_definition = event_definition
        tagged_item.sync_generic_columns()

        assert tagged_item.object_id is None
        assert tagged_item.object_uuid == event_definition.id
        assert tagged_item.content_type == ContentType.objects.get_for_model(EventDefinition)

    def test_helpers_report_the_tagged_object(self):
        insight = Insight.objects.create(filters={"events": [{"id": "$pageview"}]}, team_id=self.team.id)
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        tagged_item = TaggedItem.objects.create(insight_id=insight.id, tag_id=tag.id)

        assert tagged_item.related_object_type == "insight"
        assert tagged_item.content_object == insight

    def test_queryset_helpers_select_by_object(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dashboard")
        other_dashboard = Dashboard.objects.create(team_id=self.team.id, name="other dashboard")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)
        tagged_item = TaggedItem.objects.create(dashboard_id=dashboard.id, tag_id=tag.id)
        TaggedItem.objects.create(dashboard_id=other_dashboard.id, tag_id=tag.id)

        assert list(TaggedItem.objects.for_object(dashboard)) == [tagged_item]
        assert TaggedItem.objects.for_model(Dashboard).count() == 2
        assert list(TaggedItem.objects.for_objects(Dashboard, [dashboard.id])) == [tagged_item]
