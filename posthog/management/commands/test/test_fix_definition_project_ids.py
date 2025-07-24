from django.core.management import call_command
from django.test import TestCase
from io import StringIO
from unittest.mock import patch

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

    @patch("posthog.management.commands.fix_definition_project_ids.get_all_rollback_organization_ids")
    def test_dry_run_mode(self, mock_get_rollback_orgs):
        """Test that dry run mode doesn't make changes but reports what would be changed."""

        # Mock Redis to return our test organization
        mock_get_rollback_orgs.return_value = {str(self.organization.id)}

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
        self.assertIn("Organization: Test Organization", output)
        self.assertIn("Team: Detached Team", output)
        self.assertIn("EventDefinitions to update", output)
        self.assertIn("PropertyDefinitions to update", output)
        self.assertIn("No changes were made", output)

        # Verify no actual changes were made
        event_def.refresh_from_db()
        property_def.refresh_from_db()
        self.assertEqual(event_def.project_id, self.main_project.id)  # Should remain unchanged
        self.assertEqual(property_def.project_id, self.main_project.id)  # Should remain unchanged

    @patch("posthog.management.commands.fix_definition_project_ids.get_all_rollback_organization_ids")
    def test_actual_update_mode(self, mock_get_rollback_orgs):
        """Test that actual update mode makes the expected changes."""

        # Mock Redis to return our test organization
        mock_get_rollback_orgs.return_value = {str(self.organization.id)}

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

    @patch("posthog.management.commands.fix_definition_project_ids.get_all_rollback_organization_ids")
    def test_no_misaligned_records(self, mock_get_rollback_orgs):
        """Test behavior when all records are already correctly aligned."""

        # Mock Redis to return our test organization
        mock_get_rollback_orgs.return_value = {str(self.organization.id)}

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

    @patch("posthog.management.commands.fix_definition_project_ids.get_all_rollback_organization_ids")
    def test_mixed_property_definition_types(self, mock_get_rollback_orgs):
        """Test that the command handles different PropertyDefinition types correctly."""

        # Mock Redis to return our test organization
        mock_get_rollback_orgs.return_value = {str(self.organization.id)}

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

        # Verify all types are reported in the new summary format
        self.assertIn("Found 3 PropertyDefinitions", output)
        self.assertIn("Organization: Test Organization", output)
        self.assertIn("Team: Detached Team", output)
        self.assertIn("3 PropertyDefinitions to update", output)

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

    @patch("posthog.management.commands.fix_definition_project_ids.get_all_rollback_organization_ids")
    def test_no_rollback_organizations(self, mock_get_rollback_orgs):
        """Test behavior when no organizations have triggered rollback."""

        # Mock Redis to return empty set
        mock_get_rollback_orgs.return_value = set()

        # Create some misaligned records that would normally be fixed
        EventDefinition.objects.create(
            team=self.detached_team,
            name="test_event",
            project_id=self.main_project.id,  # Wrong project_id
        )

        # Run the command
        out = StringIO()
        call_command("fix_definition_project_ids", stdout=out)
        output = out.getvalue()

        # Verify it exits early with no work done
        self.assertIn("No organizations have triggered environment rollback", output)
        self.assertIn("Exiting", output)
        self.assertNotIn("Processing EventDefinitions", output)

    @patch("posthog.management.commands.fix_definition_project_ids.get_all_rollback_organization_ids")
    def test_filters_by_organization(self, mock_get_rollback_orgs):
        """Test that only definitions from rollback organizations are processed."""

        # Create a second organization that's not in rollback list
        other_org = Organization.objects.create(name="Other Organization")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        # Mock Redis to only return our first organization
        mock_get_rollback_orgs.return_value = {str(self.organization.id)}

        # Create misaligned records in both organizations
        rollback_event = EventDefinition.objects.create(
            team=self.detached_team,  # In rollback org
            name="rollback_event",
            project_id=self.main_project.id,  # Wrong project_id
        )

        # Create a project for the other team first
        other_project = Team.objects.create(organization=other_org, name="Other Project")
        other_team.project_id = other_project.id
        other_team.save()

        # Create a separate project to use as wrong project_id
        wrong_project = Team.objects.create(organization=other_org, name="Wrong Project")

        other_event = EventDefinition.objects.create(
            team=other_team,  # Not in rollback org
            name="other_event",
            project_id=wrong_project.id,  # Wrong project_id
        )

        # Run the command
        out = StringIO()
        call_command("fix_definition_project_ids", stdout=out)
        output = out.getvalue()

        # Verify only rollback org records were processed
        self.assertIn("Processing only rolled back organizations: 1 orgs", output)
        self.assertIn("Updated 1 EventDefinitions", output)

        # Verify the changes
        rollback_event.refresh_from_db()
        other_event.refresh_from_db()

        self.assertEqual(rollback_event.project_id, self.detached_team.project_id)  # Should be updated
        self.assertEqual(other_event.project_id, wrong_project.id)  # Should remain unchanged

    @patch("posthog.management.commands.fix_definition_project_ids.get_all_rollback_organization_ids")
    def test_batch_size_option(self, mock_get_rollback_orgs):
        """Test that batch size option works correctly."""

        # Mock Redis to return our test organization
        mock_get_rollback_orgs.return_value = {str(self.organization.id)}

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
