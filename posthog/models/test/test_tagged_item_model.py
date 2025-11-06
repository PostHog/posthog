from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError

from posthog.models import Action, Dashboard, DashboardTile, Insight, Tag, TaggedItem


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
            from products.enterprise.backend.models import EnterpriseEventDefinition
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
            from products.enterprise.backend.models import EnterprisePropertyDefinition
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
