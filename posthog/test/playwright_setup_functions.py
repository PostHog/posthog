"""Playwright setup functions for test data creation."""

import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from posthog.schema import PlaywrightWorkspaceSetupData, PlaywrightWorkspaceSetupResult

from posthog.constants import AvailableFeature
from posthog.management.commands.generate_demo_data import Command as GenerateDemoDataCommand
from posthog.models import PersonalAPIKey, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import mask_key_value


@runtime_checkable
class PlaywrightSetupFunction(Protocol):
    def __call__(self, data: BaseModel, /) -> BaseModel: ...


def create_organization_with_team(data: PlaywrightWorkspaceSetupData) -> PlaywrightWorkspaceSetupResult:
    """Creates PostHog workspace with organization, team, user, API key, and demo data."""
    org_name = data.organization_name or "Hedgebox Inc."

    # Generate unique email to avoid collisions between parallel tests
    unique_suffix = secrets.token_hex(8)  # 16 character hex string
    user_email = f"test-{unique_suffix}@posthog.com"

    # Use the working generate_demo_data command to create workspace with demo data
    command = GenerateDemoDataCommand()

    # Use fixed time for consistent test data: November 3, 2024 at noon UTC
    fixed_now = datetime(2024, 11, 3, 12, 0, 0)

    options = {
        "seed": f"playwright_test",  # constant seed
        "now": fixed_now,  # Fixed time for consistent data generation
        "days_past": 30,
        "days_future": 0,
        "n_clusters": 10,
        "dry_run": False,
        "team_id": None,
        "email": user_email,
        "password": "12345678",
        "product": "hedgebox",
        "staff": False,
        "verbosity": 0,
        "skip_materialization": True,
        "skip_dagster": True,
    }

    # Call the handle method directly - this creates org, team, user, and demo data
    command.handle(**options)

    # Get the created user, organization, and team
    user = User.objects.get(email=user_email)
    organization = user.organization
    team = user.team

    # Update organization name if custom name was provided
    if org_name != "Hedgebox Inc.":
        organization.name = org_name
        organization.save()

    # Add advanced permissions feature for password-protected sharing
    organization.available_product_features = [
        {
            "key": AvailableFeature.ADVANCED_PERMISSIONS,
            "name": AvailableFeature.ADVANCED_PERMISSIONS,
        }
    ]
    organization.save()

    # Create personal API key for the user
    api_key_value = f"phx_test_api_key_for_playwright_tests_{unique_suffix}"
    secure_value = hash_key_value(api_key_value)
    mask_value = mask_key_value(api_key_value)
    api_key, _ = PersonalAPIKey.objects.get_or_create(
        user=user,
        label="Test API Key",
        defaults={"secure_value": secure_value, "mask_value": mask_value, "scopes": ["*"]},
    )
    api_key._value = api_key_value  # type: ignore

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
        function=create_organization_with_team,  # type: ignore
        input_model=PlaywrightWorkspaceSetupData,
        description="Creates org → team + user + API key",
    ),
}
