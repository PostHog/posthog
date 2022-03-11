from django.core.exceptions import ValidationError
from django.db import IntegrityError

from ee.models import EnterpriseEventDefinition, EnterprisePropertyDefinition
from posthog.models import Action, Dashboard, Insight, Tag, TaggedItem

from .base import BaseTest


class TestTaggedItem(BaseTest):
    def test_exactly_one_object_constraint(self):
        # Setup
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        insight = Insight.objects.create(
            dashboard=dashboard, filters={"events": [{"id": "$pageview"}]}, team_id=self.team.id,
        )
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
        with self.assertRaises(IntegrityError):
            TaggedItem.objects.create(dashboard_id=dashboard.id, tag_id=tag.id)

    def test_uniqueness_constraint_insight(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        insight = Insight.objects.create(
            dashboard=dashboard, filters={"events": [{"id": "$pageview"}]}, team_id=self.team.id,
        )
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        TaggedItem.objects.create(insight_id=insight.id, tag_id=tag.id)
        with self.assertRaises(IntegrityError):
            TaggedItem.objects.create(insight_id=insight.id, tag_id=tag.id)

    def test_uniqueness_constraint_event_definition(self):
        event_definition = EnterpriseEventDefinition.objects.create(
            team=self.team, name="enterprise event", owner=self.user
        )
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        TaggedItem.objects.create(event_definition_id=event_definition.id, tag_id=tag.id)
        with self.assertRaises(IntegrityError):
            TaggedItem.objects.create(event_definition_id=event_definition.id, tag_id=tag.id)

    def test_uniqueness_constraint_property_definition(self):
        property_definition = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        TaggedItem.objects.create(property_definition_id=property_definition.id, tag_id=tag.id)
        with self.assertRaises(IntegrityError):
            TaggedItem.objects.create(property_definition_id=property_definition.id, tag_id=tag.id)

    def test_uniqueness_constraint_action(self):
        action = Action.objects.create(team=self.team, name="enterprise property")
        tag = Tag.objects.create(name="tag", team_id=self.team.id)

        TaggedItem.objects.create(action_id=action.id, tag_id=tag.id)
        with self.assertRaises(IntegrityError):
            TaggedItem.objects.create(action_id=action.id, tag_id=tag.id)
