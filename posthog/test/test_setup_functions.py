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


def setup_basic_organization(data: BasicOrganizationSetupData) -> BasicOrganizationSetupResult:
    """
    Creates a basic organization with a project and team for testing.
    Also creates/updates the test@posthog.com user and adds them to the organization.

    Args:
        data: Request data (can contain custom org/project names)

    Returns:
        Dict with created organization, project, team IDs and user info
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


def setup_insights_test(data: InsightsTestSetupData) -> InsightsTestSetupResult:
    """
    Sets up data for insights/analytics testing.

    Args:
        data: Request data (can contain insight configurations)

    Returns:
        Dict with created insights test data
    """
    # First create basic org structure
    org_data = setup_basic_organization(data)

    # Add insights/events setup here when needed
    # This is a placeholder for insights specific setup

    return {**org_data, "insights_setup": True, "message": "Insights test environment ready"}


# Registry of all available test setup functions
TEST_SETUP_FUNCTIONS: dict[str, Callable[[Any], Any]] = {
    "basic_organization": setup_basic_organization,
    "insights_test": setup_insights_test,
}
