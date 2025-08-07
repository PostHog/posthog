"""Playwright setup functions for test data creation."""

import datetime as dt
import secrets
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from pydantic import BaseModel

from posthog.models import PersonalAPIKey
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import mask_key_value
from posthog.schema import PlaywrightWorkspaceSetupData, PlaywrightWorkspaceSetupResult
from posthog.demo.matrix import MatrixManager
from posthog.demo.products.hedgebox import HedgeboxMatrix


@runtime_checkable
class PlaywrightSetupFunction(Protocol):
    def __call__(self, data: BaseModel, /) -> BaseModel: ...


def create_organization_with_team(data: PlaywrightWorkspaceSetupData) -> PlaywrightWorkspaceSetupResult:
    """Creates PostHog workspace with organization, team, user, API key, and demo data."""
    org_name = data.organization_name or "Test Organization"

    # Generate unique email to avoid collisions between parallel tests
    unique_suffix = secrets.token_hex(8)  # 16 character hex string
    user_email = f"test-{unique_suffix}@posthog.com"

    # Create Matrix with demo data (using smaller dataset for tests)
    now = dt.datetime.now(dt.UTC)
    matrix = HedgeboxMatrix(
        seed="playwright_test_seed",
        now=now,
        days_past=30,  # Smaller dataset for faster tests
        days_future=0,  # No future events for tests
        n_clusters=10,  # Much smaller than default 500
    )

    # Use MatrixManager to create workspace with demo data
    matrix_manager = MatrixManager(matrix, print_steps=False)  # Quiet for tests

    organization, team, user = matrix_manager.ensure_account_and_save(
        email=user_email,
        first_name="Test User",
        organization_name=org_name,
        password="12345678",
        is_staff=False,
        disallow_collision=True,  # Each test gets a fresh user
    )

    # Create personal API key for the user
    api_key_value = f"phx_test_api_key_for_playwright_tests_{unique_suffix}"
    secure_value = hash_key_value(api_key_value)
    mask_value = mask_key_value(api_key_value)
    api_key, _ = PersonalAPIKey.objects.get_or_create(
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
