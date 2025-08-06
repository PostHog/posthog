"""
Registry of test setup functions for Playwright tests.
Each function takes request data and returns setup results.
"""

from typing import Any
from collections.abc import Callable

from django.contrib.auth.models import User
from django.db import transaction

from posthog.models import Organization, Project, Team


def setup_basic_organization(data: dict[str, Any]) -> dict[str, Any]:
    """
    Creates a basic organization with a project and team for testing.

    Args:
        data: Request data (can contain custom org/project names)

    Returns:
        Dict with created organization, project, and team IDs
    """
    org_name = data.get("organization_name", "Test Organization")
    project_name = data.get("project_name", "Test Project")

    with transaction.atomic():
        # Create organization
        organization = Organization.objects.create(name=org_name, slug=f"test-org-{org_name.lower().replace(' ', '-')}")

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
        }


def setup_user_with_organization(data: dict[str, Any]) -> dict[str, Any]:
    """
    Creates a test user with an organization.

    Args:
        data: Request data (can contain user email, password, org name)

    Returns:
        Dict with created user and organization details
    """
    email = data.get("email", "test@posthog.com")
    password = data.get("password", "testpassword123")
    org_name = data.get("organization_name", "Test Organization")

    with transaction.atomic():
        # Create user
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=data.get("first_name", "Test"),
            last_name=data.get("last_name", "User"),
        )

        # Create organization
        organization = Organization.objects.create(name=org_name, slug=f"test-org-{org_name.lower().replace(' ', '-')}")

        # Add user to organization
        organization.members.add(user)

        return {
            "user_id": str(user.id),
            "user_email": user.email,
            "organization_id": str(organization.id),
            "organization_name": organization.name,
        }


def setup_empty_database(data: dict[str, Any]) -> dict[str, Any]:
    """
    Clears all test data (for clean slate tests).

    Args:
        data: Request data (unused)

    Returns:
        Dict with cleanup confirmation
    """
    with transaction.atomic():
        # Clear main models (in dependency order)
        Team.objects.all().delete()
        Project.objects.all().delete()
        Organization.objects.all().delete()

        # Clear users (except superusers to avoid breaking admin access)
        User.objects.filter(is_superuser=False).delete()

        return {"cleared": True, "message": "Test database cleared successfully"}


def setup_feature_flags_test(data: dict[str, Any]) -> dict[str, Any]:
    """
    Sets up data for feature flags testing.

    Args:
        data: Request data (can contain flag configurations)

    Returns:
        Dict with created feature flag details
    """
    # First create basic org structure
    org_data = setup_basic_organization(data)

    # Add feature flags setup here when needed
    # This is a placeholder for feature flag specific setup

    return {**org_data, "feature_flags_setup": True, "message": "Feature flags test environment ready"}


def setup_insights_test(data: dict[str, Any]) -> dict[str, Any]:
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
TEST_SETUP_FUNCTIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "basic_organization": setup_basic_organization,
    "user_with_organization": setup_user_with_organization,
    "empty_database": setup_empty_database,
    "feature_flags_test": setup_feature_flags_test,
    "insights_test": setup_insights_test,
}
