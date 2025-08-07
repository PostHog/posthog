"""Playwright setup functions for test data creation."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from pydantic import BaseModel

from django.db import transaction
from posthog.api.personal_api_key import PersonalAPIKeySerializer
from posthog.models import Organization, Team, User
from posthog.schema import BasicOrganizationSetupData, BasicOrganizationSetupResult


@runtime_checkable
class PlaywrightSetupFunction(Protocol):
    def __call__(self, data: BaseModel, /) -> BaseModel: ...


def create_organization_with_team(data: BasicOrganizationSetupData) -> BasicOrganizationSetupResult:
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

        mock_request = type("MockRequest", (), {"user": user})()
        serializer = PersonalAPIKeySerializer(context={"request": mock_request})
        api_key = serializer.create({"label": "Test API Key", "scopes": ["*"]})

        return BasicOrganizationSetupResult(
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
        input_model=BasicOrganizationSetupData,
        description="Creates org → team + user + API key",
    ),
}
