"""
Registry of playwright setup functions for Playwright tests.
Each function takes request data and returns setup results.
"""

from typing import Any
from collections.abc import Callable

from django.db import transaction

from posthog.models import Organization, Project, Team, PersonalAPIKey, User
from posthog.schema import (
    BasicOrganizationSetupData,
    BasicOrganizationSetupResult,
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
    org_name = data.organization_name or "Test Organization"
    project_name = data.project_name or "Test Project"

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

        # Create personal API key for the user
        test_key_value = "phx_test_api_key_123456789"  # Fixed test API key for consistency
        from posthog.models.personal_api_key import hash_key_value
        from posthog.models.utils import mask_key_value

        api_key = PersonalAPIKey.objects.create(
            label="Test API Key",
            user=user,
            secure_value=hash_key_value(test_key_value),
            mask_value=mask_key_value(test_key_value),
        )
        # Set the plaintext value for immediate use (matches API creation pattern)
        api_key._value = test_key_value

        return BasicOrganizationSetupResult(
            organization_id=str(organization.id),
            project_id=str(project.id),
            team_id=str(team.id),
            organization_name=organization.name,
            project_name=project.name,
            team_name=team.name,
            user_id=str(user.id),
            user_email=user.email,
            personal_api_key=test_key_value,  # Return the actual plaintext key value
        )


# Registry of all available playwright setup functions
# Maps endpoint names to their implementation functions
PLAYWRIGHT_SETUP_FUNCTIONS: dict[str, Callable[[Any], Any]] = {
    "organization_with_team": create_organization_with_team,  # Creates org → project → team + user + API key
}
