from io import StringIO

from posthog.test.base import APIBaseTest

from django.core.management import call_command

from parameterized import parameterized

from posthog.hogql_queries.ai.utils import HEAVY_PROPERTY_NAMES
from posthog.models.team import Team

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.event_definitions.backend.models.event_definition import EventDefinition
from products.event_definitions.backend.models.event_property import EventProperty
from products.event_definitions.backend.models.property_definition import PropertyDefinition


class TestAIPropertyDefinitionRepair(APIBaseTest):
    @parameterized.expand([(False,), (True,)])
    def test_repair_preserves_existing_definitions_and_permissions(self, apply: bool) -> None:
        EventDefinition.objects.create(team=self.team, project=self.team.project, name="$ai_generation")
        existing = PropertyDefinition.objects.create(
            team=self.team,
            name="$ai_input",
            type=PropertyDefinition.Type.EVENT,
            property_type="String",
        )
        rule = PropertyAccessControl.objects.create(team=self.team, property_definition=existing, access_level="none")
        other_team = Team.objects.create(organization=self.organization)
        EventDefinition.objects.create(team=other_team, project=other_team.project, name="$ai_generation")

        for _ in range(2):
            call_command("repair_ai_property_definitions", team_id=self.team.id, apply=apply, stdout=StringIO())

        definitions = PropertyDefinition.objects.filter(team=self.team, type=PropertyDefinition.Type.EVENT)
        self.assertEqual(
            set(definitions.values_list("name", flat=True)), HEAVY_PROPERTY_NAMES if apply else {"$ai_input"}
        )
        self.assertEqual(definitions.count(), len(HEAVY_PROPERTY_NAMES) if apply else 1)
        existing.refresh_from_db()
        rule.refresh_from_db()
        self.assertEqual(existing.property_type, "String")
        self.assertEqual(rule.property_definition_id, existing.id)
        self.assertEqual(rule.access_level, "none")
        self.assertFalse(EventProperty.objects.filter(team=self.team).exists())
        self.assertFalse(PropertyDefinition.objects.filter(team=other_team).exists())
        if apply:
            self.assertFalse(definitions.exclude(id=existing.id).exclude(property_type=None).exists())
            response = self.client.get(
                f"/api/projects/{self.team.id}/property_definitions/", {"type": "event", "search": "$ai_"}
            )
            self.assertEqual(response.status_code, 200)
            selectable = {definition["name"]: definition["id"] for definition in response.json()["results"]}
            self.assertEqual(set(selectable), HEAVY_PROPERTY_NAMES)
            self.assertEqual(selectable["$ai_input"], str(existing.id))

    def test_repair_reuses_project_definitions_from_another_team(self) -> None:
        sibling = Team.objects.create(organization=self.organization, project=self.team.project)
        EventDefinition.objects.create(team=sibling, project=self.team.project, name="$ai_span")
        existing = PropertyDefinition.objects.create(
            team=sibling, project=self.team.project, name="$ai_input", type=PropertyDefinition.Type.EVENT
        )

        call_command("repair_ai_property_definitions", team_id=self.team.id, apply=True, stdout=StringIO())

        self.assertEqual(
            PropertyDefinition.objects.filter(project=self.team.project).count(), len(HEAVY_PROPERTY_NAMES)
        )
        self.assertEqual(PropertyDefinition.objects.get(project=self.team.project, name="$ai_input").id, existing.id)

    def test_repair_does_not_seed_a_project_without_ai_events(self) -> None:
        EventDefinition.objects.create(team=self.team, project=self.team.project, name="$pageview")

        call_command("repair_ai_property_definitions", team_id=self.team.id, apply=True, stdout=StringIO())

        self.assertFalse(PropertyDefinition.objects.filter(team=self.team).exists())
