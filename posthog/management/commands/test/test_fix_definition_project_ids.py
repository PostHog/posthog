from django.core.management import call_command
from django.test import TestCase
from io import StringIO

from posthog.models import Organization, Team, EventDefinition, PropertyDefinition


class TestFixDefinitionProjectIds(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Organization")

        # Create main project team
        self.main_project = Team.objects.create(organization=self.organization, name="Main Project")

        # Create secondary environment team in main project
        self.staging_env = Team.objects.create(
            organization=self.organization, name="Staging", project_id=self.main_project.id
        )

        # Create a detached project team (team.id == team.project_id)
        self.detached_team = Team.objects.create(organization=self.organization, name="Detached Team")
        # Simulate a team that was moved to its own project
        self.detached_team.project_id = self.detached_team.id
        self.detached_team.save()

    def test_dry_run_mode(self):
        """Test that dry run mode doesn't make changes but reports what would be changed."""

        # Create misaligned EventDefinition
        event_def = EventDefinition.objects.create(
            team=self.detached_team,
            name="test_event",
            project_id=self.main_project.id,  # Wrong project_id
        )

        # Create misaligned PropertyDefinition
        property_def = PropertyDefinition.objects.create(
            team=self.detached_team,
            name="test_property",
            type=PropertyDefinition.Type.EVENT,
            project_id=self.main_project.id,  # Wrong project_id
        )

        # Run dry run
        out = StringIO()
        call_command("fix_definition_project_ids", "--dry-run", stdout=out)
        output = out.getvalue()

        # Verify output contains dry run information
        self.assertIn("DRY RUN MODE", output)
        self.assertIn("Found 1 EventDefinitions", output)
        self.assertIn("Found 1 PropertyDefinitions", output)
        self.assertIn("Would update EventDefinition", output)
        self.assertIn("Would update PropertyDefinition", output)
        self.assertIn("No changes were made", output)

        # Verify no actual changes were made
        event_def.refresh_from_db()
        property_def.refresh_from_db()
        self.assertEqual(event_def.project_id, self.main_project.id)  # Should remain unchanged
        self.assertEqual(property_def.project_id, self.main_project.id)  # Should remain unchanged

    def test_actual_update_mode(self):
        """Test that actual update mode makes the expected changes."""

        # Create misaligned EventDefinition
        event_def = EventDefinition.objects.create(
            team=self.detached_team,
            name="test_event",
            project_id=self.main_project.id,  # Wrong project_id
        )

        # Create misaligned PropertyDefinition
        property_def = PropertyDefinition.objects.create(
            team=self.detached_team,
            name="test_property",
            type=PropertyDefinition.Type.EVENT,
            project_id=self.main_project.id,  # Wrong project_id
        )

        # Create correctly aligned definitions (should not be touched)
        correct_event_def = EventDefinition.objects.create(
            team=self.staging_env,
            name="correct_event",
            project_id=self.main_project.id,  # Correct project_id
        )

        # Run the command
        out = StringIO()
        call_command("fix_definition_project_ids", stdout=out)
        output = out.getvalue()

        # Verify output shows updates
        self.assertIn("Updated 1 EventDefinitions", output)
        self.assertIn("Updated 1 PropertyDefinitions", output)
        self.assertIn("Successfully aligned 2 definition records", output)

        # Verify the changes were made
        event_def.refresh_from_db()
        property_def.refresh_from_db()
        correct_event_def.refresh_from_db()

        self.assertEqual(event_def.project_id, self.detached_team.project_id)  # Should be updated
        self.assertEqual(property_def.project_id, self.detached_team.project_id)  # Should be updated
        self.assertEqual(correct_event_def.project_id, self.main_project.id)  # Should remain unchanged

    def test_no_misaligned_records(self):
        """Test behavior when all records are already correctly aligned."""

        # Create correctly aligned definitions
        EventDefinition.objects.create(
            team=self.staging_env,
            name="correct_event",
            project_id=self.main_project.id,  # Correct project_id
        )

        PropertyDefinition.objects.create(
            team=self.staging_env,
            name="correct_property",
            type=PropertyDefinition.Type.EVENT,
            project_id=self.main_project.id,  # Correct project_id
        )

        # Run the command
        out = StringIO()
        call_command("fix_definition_project_ids", stdout=out)
        output = out.getvalue()

        # Verify output shows no updates needed
        self.assertIn("No EventDefinitions need project_id alignment", output)
        self.assertIn("No PropertyDefinitions need project_id alignment", output)
        self.assertIn("All definition records were already aligned", output)

    def test_mixed_property_definition_types(self):
        """Test that the command handles different PropertyDefinition types correctly."""

        # Create misaligned PropertyDefinitions of different types
        event_prop = PropertyDefinition.objects.create(
            team=self.detached_team,
            name="event_property",
            type=PropertyDefinition.Type.EVENT,
            project_id=self.main_project.id,  # Wrong project_id
        )

        person_prop = PropertyDefinition.objects.create(
            team=self.detached_team,
            name="person_property",
            type=PropertyDefinition.Type.PERSON,
            project_id=self.main_project.id,  # Wrong project_id
        )

        group_prop = PropertyDefinition.objects.create(
            team=self.detached_team,
            name="group_property",
            type=PropertyDefinition.Type.GROUP,
            group_type_index=0,
            project_id=self.main_project.id,  # Wrong project_id
        )

        # Run dry run to see the output
        out = StringIO()
        call_command("fix_definition_project_ids", "--dry-run", stdout=out)
        output = out.getvalue()

        # Verify all types are reported
        self.assertIn("Found 3 PropertyDefinitions", output)
        self.assertIn("type=event", output)
        self.assertIn("type=person", output)
        self.assertIn("type=group", output)

        # Run actual update
        out = StringIO()
        call_command("fix_definition_project_ids", stdout=out)

        # Verify all were updated
        event_prop.refresh_from_db()
        person_prop.refresh_from_db()
        group_prop.refresh_from_db()

        self.assertEqual(event_prop.project_id, self.detached_team.project_id)
        self.assertEqual(person_prop.project_id, self.detached_team.project_id)
        self.assertEqual(group_prop.project_id, self.detached_team.project_id)

    def test_batch_size_option(self):
        """Test that batch size option works correctly."""

        # Create multiple misaligned records
        for i in range(5):
            EventDefinition.objects.create(
                team=self.detached_team,
                name=f"test_event_{i}",
                project_id=self.main_project.id,  # Wrong project_id
            )

        # Run with small batch size
        out = StringIO()
        call_command("fix_definition_project_ids", "--batch-size", "2", stdout=out)
        output = out.getvalue()

        # Should show batch processing progress
        self.assertIn("Batch size: 2", output)
        # Check that some updates were made (the exact count may vary due to batching logic)
        self.assertIn("Updated", output)
        self.assertIn("EventDefinitions", output)

        # Verify all records were updated
        updated_count = EventDefinition.objects.filter(
            team=self.detached_team, project_id=self.detached_team.project_id
        ).count()
        self.assertEqual(updated_count, 5)
