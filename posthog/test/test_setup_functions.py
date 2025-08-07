"""
Registry of test setup functions for Playwright tests.
Each function takes request data and returns setup results.
"""

from typing import Any
from collections.abc import Callable

from django.contrib.auth.models import User
from django.db import transaction

from posthog.models import Organization, Project, Team
from posthog.schema import (
    BasicOrganizationSetupData,
    BasicOrganizationSetupResult,
    InsightsTestSetupData,
    InsightsTestSetupResult,
)


def create_organization_with_team(data: BasicOrganizationSetupData) -> BasicOrganizationSetupResult:
    """
    Creates a complete PostHog workspace: Organization → Project → Team + test@posthog.com user.

    This sets up the full hierarchy that PostHog needs:
    - Organization (top-level company/account)
    - Project (within the organization)
    - Team/Environment (within the project - where actual data lives)
    - User (test@posthog.com) who is a member of the organization

    Args:
        data: Optional org/project names (defaults to "Test Organization"/"Test Project")

    Returns:
        All created IDs and details for the test workspace
    """
    org_name = data.get("organization_name", "Test Organization")
    project_name = data.get("project_name", "Test Project")

    with transaction.atomic():
        # Create or get the test user
        user, created = User.objects.get_or_create(
            email="test@posthog.com",
            defaults={"username": "test@posthog.com", "first_name": "Test", "last_name": "User"},
        )
        if created or not user.check_password("12345678"):
            user.set_password("12345678")
            user.save()

        # Create organization
        organization = Organization.objects.create(name=org_name, slug=f"test-org-{org_name.lower().replace(' ', '-')}")

        # Add user to organization
        organization.members.add(user)

        # Create project
        project = Project.objects.create(name=project_name, organization=organization)

        # Create team (environment)
        team = Team.objects.create(name=f"{project_name} Default", project=project, organization=organization)

        return {
            "organization_id": str(organization.id),
            "project_id": str(project.id),
            "team_id": str(team.id),
            "organization_name": organization.name,
            "project_name": project.name,
            "team_name": team.name,
            "user_id": str(user.id),
            "user_email": user.email,
        }


def create_analytics_workspace(data: InsightsTestSetupData) -> InsightsTestSetupResult:
    """
    Creates a workspace with sample analytics data for testing insights/dashboards.

    Sets up:
    - Complete organization + project + team (via create_organization_with_team)
    - Sample events and analytics data (placeholder for now)

    Args:
        data: Analytics configuration (event counts, date ranges, etc.)

    Returns:
        Workspace details + analytics setup confirmation
    """
    # Create the base workspace first
    workspace_data = create_organization_with_team(data)

    # TODO: Add sample events/analytics data here when needed
    # Could create sample events, users, properties, etc.

    return {**workspace_data, "analytics_ready": True, "message": "Analytics workspace ready for testing"}


# Registry of all available workspace setup functions
# Maps endpoint names to their implementation functions
TEST_SETUP_FUNCTIONS: dict[str, Callable[[Any], Any]] = {
    "organization_with_team": create_organization_with_team,  # Creates org → project → team + user
    "analytics_workspace": create_analytics_workspace,  # Above + sample analytics data
}
