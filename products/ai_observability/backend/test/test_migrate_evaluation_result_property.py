from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from products.event_definitions.backend.models.property_definition import PropertyDefinition


class TestMigrateEvaluationResultProperty(BaseTest):
    def test_retypes_only_event_results_and_can_resume(self) -> None:
        second_team = self.organization.teams.create(name="Another project")
        event = PropertyDefinition.objects.create(team=self.team, name="$ai_evaluation_result", property_type="Boolean")
        numeric = PropertyDefinition.objects.create(
            team=second_team, name="$ai_evaluation_result", property_type="Numeric", is_numerical=True
        )
        person = PropertyDefinition.objects.create(
            team=self.team, name="$ai_evaluation_result", type=PropertyDefinition.Type.PERSON, property_type="Boolean"
        )
        other = PropertyDefinition.objects.create(team=self.team, name="another_result", property_type="Boolean")

        output = StringIO()
        call_command("migrate_evaluation_result_property", stdout=output)
        self.assertIn("Would update 2", output.getvalue())
        event.refresh_from_db()
        self.assertEqual(event.property_type, "Boolean")

        call_command("migrate_evaluation_result_property", apply=True, batch_size=1, stdout=StringIO())
        for definition in (event, numeric):
            definition.refresh_from_db()
            self.assertEqual(definition.property_type, "String")
            self.assertFalse(definition.is_numerical)
        for definition in (person, other):
            definition.refresh_from_db()
            self.assertEqual(definition.property_type, "Boolean")

        output = StringIO()
        call_command("migrate_evaluation_result_property", apply=True, stdout=output)
        self.assertIn("Updated 0", output.getvalue())
