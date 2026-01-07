import re
from io import StringIO

from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from posthog.models import EventDefinition, GroupTypeMapping, Organization, PropertyDefinition, Team
from posthog.test.test_utils import create_group_type_mapping_without_created_at


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

        # Create misaligned GroupTypeMapping
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.detached_team,
            group_type="organization",
            group_type_index=0,
            project_id=self.main_project.id,  # Wrong project_id
        )

        # Run dry run
        out = StringIO()
        call_command("fix_definition_project_ids", "--dry-run", stdout=out)
        output = out.getvalue()

        # Verify output contains dry run information
        assert "DRY RUN MODE" in output
        assert "Found 1 EventDefinitions" in output
        assert "Found 1 PropertyDefinitions" in output
        assert "Found 1 GroupTypeMappings" in output
        assert "Organization: Test Organization" in output
        assert "Team: Detached Team" in output
        assert "EventDefinitions to update" in output
        assert "PropertyDefinitions to update" in output
        assert "GroupTypeMappings to update" in output
        assert "No changes were made" in output

        # Verify no actual changes were made
        event_def.refresh_from_db()
        property_def.refresh_from_db()
        group_type_mapping.refresh_from_db()
        assert event_def.project_id == self.main_project.id  # Should remain unchanged
        assert property_def.project_id == self.main_project.id  # Should remain unchanged
        assert group_type_mapping.project_id == self.main_project.id  # Should remain unchanged

    @patch("posthog.management.commands.fix_definition_project_ids.get_all_rollback_organization_ids")
    def test_actual_update_mode(self, mock_get_rollback_orgs):
        """Test that actual update mode makes the expected changes."""

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

        # Create misaligned GroupTypeMapping
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.detached_team,
            group_type="organization",
            group_type_index=0,
            project_id=self.main_project.id,  # Wrong project_id
        )

        # Create correctly aligned definitions (should not be touched)
        correct_event_def = EventDefinition.objects.create(
            team=self.staging_env,
            name="correct_event",
            project_id=self.main_project.id,  # Correct project_id
        )

        correct_group_type = create_group_type_mapping_without_created_at(
            team=self.staging_env,
            group_type="company",
            group_type_index=1,
            project_id=self.main_project.id,  # Correct project_id
        )

        # Run the command
        out = StringIO()
        call_command("fix_definition_project_ids", stdout=out)
        output = out.getvalue()

        # Verify output shows updates
        assert "Updated 1 EventDefinitions" in output
        assert "Updated 1 PropertyDefinitions" in output
        assert "Updated 1 GroupTypeMappings" in output
        assert "Successfully aligned 3 definition records" in output

        # Verify the changes were made
        event_def.refresh_from_db()
        property_def.refresh_from_db()
        group_type_mapping.refresh_from_db()
        correct_event_def.refresh_from_db()
        correct_group_type.refresh_from_db()

        assert event_def.project_id == self.detached_team.project_id  # Should be updated
        assert property_def.project_id == self.detached_team.project_id  # Should be updated
        assert group_type_mapping.project_id == self.detached_team.project_id  # Should be updated
        assert correct_event_def.project_id == self.main_project.id  # Should remain unchanged
        assert correct_group_type.project_id == self.main_project.id  # Should remain unchanged

    @patch("posthog.management.commands.fix_definition_project_ids.get_all_rollback_organization_ids")
    def test_no_misaligned_records(self, mock_get_rollback_orgs):
        """Test behavior when all records are already correctly aligned."""

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

        create_group_type_mapping_without_created_at(
            team=self.staging_env,
            group_type="organization",
            group_type_index=0,
            project_id=self.main_project.id,  # Correct project_id
        )

        # Run the command
        out = StringIO()
        call_command("fix_definition_project_ids", stdout=out)
        output = out.getvalue()

        # Verify output shows no updates needed
        assert "No EventDefinitions need project_id alignment" in output
        assert "No PropertyDefinitions need project_id alignment" in output
        assert "No GroupTypeMappings need project_id alignment" in output
        assert "All definition records were already aligned" in output

    @patch("posthog.management.commands.fix_definition_project_ids.get_all_rollback_organization_ids")
    def test_mixed_property_definition_types(self, mock_get_rollback_orgs):
        """Test that the command handles different PropertyDefinition types correctly."""

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
        assert "Found 3 PropertyDefinitions" in output
        assert "Organization: Test Organization" in output
        assert "Team: Detached Team" in output
        assert "3 PropertyDefinitions to update" in output

        # Run actual update
        out = StringIO()
        call_command("fix_definition_project_ids", stdout=out)

        # Verify all were updated
        event_prop.refresh_from_db()
        person_prop.refresh_from_db()
        group_prop.refresh_from_db()

        assert event_prop.project_id == self.detached_team.project_id
        assert person_prop.project_id == self.detached_team.project_id
        assert group_prop.project_id == self.detached_team.project_id

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
        assert "No organizations have triggered environment rollback" in output
        assert "Exiting" in output
        assert "Processing EventDefinitions" not in output

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
        assert "Processing only rolled back organizations: 1 orgs" in output
        assert "Updated 1 EventDefinitions" in output

        # Verify the changes
        rollback_event.refresh_from_db()
        other_event.refresh_from_db()

        assert rollback_event.project_id == self.detached_team.project_id  # Should be updated
        assert other_event.project_id == wrong_project.id  # Should remain unchanged

    @patch("posthog.management.commands.fix_definition_project_ids.get_all_rollback_organization_ids")
    def test_batch_size_option(self, mock_get_rollback_orgs):
        """Test that batch size option works correctly."""

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
        assert "Batch size: 2" in output
        # Check that some updates were made (the exact count may vary due to batching logic)
        assert "Updated" in output
        assert "EventDefinitions" in output

        # Verify all records were updated
        updated_count = EventDefinition.objects.filter(
            team=self.detached_team, project_id=self.detached_team.project_id
        ).count()
        assert updated_count == 5

    @patch("posthog.management.commands.fix_definition_project_ids.get_all_rollback_organization_ids")
    def test_group_type_mapping_with_unique_constraints(self, mock_get_rollback_orgs):
        """Test that GroupTypeMapping alignment respects unique constraints."""

        mock_get_rollback_orgs.return_value = {str(self.organization.id)}

        # Create multiple teams with misaligned GroupTypeMappings
        team1 = Team.objects.create(organization=self.organization, name="Team 1")
        team2 = Team.objects.create(organization=self.organization, name="Team 2")

        # Create misaligned GroupTypeMappings with same group_type and group_type_index
        # but different teams (so different projects after alignment)
        # We need to use different projects for the wrong project_id to avoid unique constraint violations
        wrong_project1 = Team.objects.create(organization=self.organization, name="Wrong Project 1")
        wrong_project2 = Team.objects.create(organization=self.organization, name="Wrong Project 2")

        gtm1 = create_group_type_mapping_without_created_at(
            team=team1,
            group_type="organization",
            group_type_index=0,
            project_id=wrong_project1.id,  # Wrong project_id
        )

        gtm2 = create_group_type_mapping_without_created_at(
            team=team2,
            group_type="organization",
            group_type_index=0,
            project_id=wrong_project2.id,  # Wrong project_id
        )

        # Also create one with different group_type_index
        gtm3 = create_group_type_mapping_without_created_at(
            team=team1,
            group_type="company",
            group_type_index=1,
            project_id=wrong_project1.id,  # Wrong project_id
        )

        # Run the command
        out = StringIO()
        call_command("fix_definition_project_ids", stdout=out)
        output = out.getvalue()

        # Verify output shows updates
        assert "Updated 3 GroupTypeMappings" in output

        # Verify the changes were made correctly
        gtm1.refresh_from_db()
        gtm2.refresh_from_db()
        gtm3.refresh_from_db()

        assert gtm1.project_id == team1.project_id
        assert gtm2.project_id == team2.project_id
        assert gtm3.project_id == team1.project_id

        # Verify unique constraints are still respected
        # Each team/project should have unique (project, group_type) and (project, group_type_index)
        team1_mappings = GroupTypeMapping.objects.filter(project_id=team1.project_id)
        team2_mappings = GroupTypeMapping.objects.filter(project_id=team2.project_id)

        assert team1_mappings.count() == 2  # gtm1 and gtm3
        assert team2_mappings.count() == 1  # gtm2

        # Verify no duplicate group_type_index within same project
        team1_indices = set(team1_mappings.values_list("group_type_index", flat=True))
        assert len(team1_indices) == 2  # Should have 2 unique indices
