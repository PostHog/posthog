"""Playwright setup functions for test data creation."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from pydantic import BaseModel

from django.db import transaction
from posthog.models import Organization, Team, User, PersonalAPIKey
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import mask_key_value
from posthog.schema import PlaywrightWorkspaceSetupData, PlaywrightWorkspaceSetupResult


@runtime_checkable
class PlaywrightSetupFunction(Protocol):
    def __call__(self, data: BaseModel, /) -> BaseModel: ...


def create_organization_with_team(data: PlaywrightWorkspaceSetupData) -> PlaywrightWorkspaceSetupResult:
    """Creates PostHog workspace with organization, team, user, and API key."""
    org_name = data.organization_name or "Test Organization"

    with transaction.atomic():
        user, created = User.objects.get_or_create(
            email="test@posthog.com",
            defaults={"first_name": "Test", "last_name": "User"},
        )
        if created or not user.check_password("12345678"):
            user.set_password("12345678")
            user.save()

        organization = Organization.objects.create(name=org_name, slug=f"test-org-{org_name.lower().replace(' ', '-')}")
        organization.members.add(user)

        team = Team.objects.create(name="Default Team", organization=organization)

        # Use a constant API key value for consistent testing
        api_key_value = "phx_test_api_key_for_playwright_tests_123456789"
        mask_value = mask_key_value(api_key_value)
        secure_value = hash_key_value(api_key_value)

        # Get or create the API key to avoid hitting the 10 key limit
        api_key, created = PersonalAPIKey.objects.get_or_create(
            user=user,
            label="Test API Key",
            defaults={"secure_value": secure_value, "mask_value": mask_value, "scopes": ["*"]},
        )
        api_key._value = api_key_value

        return PlaywrightWorkspaceSetupResult(
            organization_id=str(organization.id),
            team_id=str(team.id),
            organization_name=organization.name,
            team_name=team.name,
            user_id=str(user.id),
            user_email=user.email,
            personal_api_key=api_key._value,  # type: ignore
        )


@dataclass(frozen=True)
class SetupFunctionConfig:
    function: PlaywrightSetupFunction
    input_model: type[BaseModel]
    description: str


PLAYWRIGHT_SETUP_FUNCTIONS: dict[str, SetupFunctionConfig] = {
    "organization_with_team": SetupFunctionConfig(
        function=create_organization_with_team,
        input_model=PlaywrightWorkspaceSetupData,
        description="Creates org → team + user + API key",
    ),
}
