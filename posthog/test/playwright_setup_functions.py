"""
Registry of playwright setup functions for Playwright tests.
Each function takes a Pydantic BaseModel subclass and returns a Pydantic BaseModel subclass.
"""

from typing import Protocol
from pydantic import BaseModel

from django.db import transaction
from posthog.api.personal_api_key import PersonalAPIKeySerializer

from posthog.models import Organization, Team, User
from posthog.schema import (
    BasicOrganizationSetupData,
    BasicOrganizationSetupResult,
)


class PlaywrightSetupFunction(Protocol):
    """Protocol for playwright setup functions - takes and returns BaseModel subclasses"""

    def __call__(self, data: BaseModel) -> BaseModel: ...


def create_organization_with_team(data: BasicOrganizationSetupData) -> BasicOrganizationSetupResult:
    """
    Creates a complete PostHog workspace: Organization → Team + test@posthog.com user.

    This sets up the hierarchy that PostHog needs:
    - Organization (top-level company/account)
    - Team/Environment (where actual data lives)
    - User (test@posthog.com) who is a member of the organization

    Args:
        data: Optional org name (defaults to "Test Organization")

    Returns:
        All created IDs and details for the test workspace
    """
    org_name = data.organization_name or "Test Organization"

    with transaction.atomic():
        # Create or get the test user (PostHog User model uses email as username)
        user, created = User.objects.get_or_create(
            email="test@posthog.com",
            defaults={"first_name": "Test", "last_name": "User"},
        )
        if created or not user.check_password("12345678"):
            user.set_password("12345678")
            user.save()

        organization = Organization.objects.create(name=org_name, slug=f"test-org-{org_name.lower().replace(' ', '-')}")
        organization.members.add(user)

        # Create team
        team = Team.objects.create(name="Default Team", organization=organization)

        # Mock a request context with the user
        mock_request = type("MockRequest", (), {"user": user})()
        serializer = PersonalAPIKeySerializer(context={"request": mock_request})
        api_key = serializer.create({"label": "Test API Key", "scopes": ["*"]})

        return BasicOrganizationSetupResult(
            organization_id=str(organization.id),
            project_id="",  # Not used, but required by schema
            team_id=str(team.id),
            organization_name=organization.name,
            project_name="",  # Not used, but required by schema
            team_name=team.name,
            user_id=str(user.id),
            user_email=user.email,
            personal_api_key=api_key._value,  # type: ignore  # Return the generated token
        )


# Registry of all available playwright setup functions
# Maps endpoint names to their implementation functions
# Each function takes a BaseModel subclass and returns a BaseModel subclass
PLAYWRIGHT_SETUP_FUNCTIONS: dict[str, PlaywrightSetupFunction] = {
    "organization_with_team": create_organization_with_team,  # Creates org → project → team + user + API key
}
