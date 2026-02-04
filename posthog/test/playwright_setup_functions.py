"""Playwright setup functions for test data creation."""

import logging
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

import psutil
from django.utils import timezone

from pydantic import BaseModel

from posthog.schema import PlaywrightWorkspaceSetupData, PlaywrightWorkspaceSetupResult

from posthog.constants import AvailableFeature
from posthog.management.commands.generate_demo_data import Command as GenerateDemoDataCommand
from posthog.models import PersonalAPIKey, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import mask_key_value

logger = logging.getLogger(__name__)


def log_timing_and_resources(label: str, start_time: float | None = None) -> float:
    """Log timing and system resource usage for diagnostics."""
    current_time = time.monotonic()
    elapsed = (current_time - start_time) * 1000 if start_time else 0

    # Get system resource info
    try:
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        cpu_percent = process.cpu_percent(interval=None)
        system_mem = psutil.virtual_memory()

        resource_info = (
            f"rss={mem_info.rss / 1024 / 1024:.1f}MB, "
            f"vms={mem_info.vms / 1024 / 1024:.1f}MB, "
            f"cpu={cpu_percent:.1f}%, "
            f"system_mem={system_mem.percent:.1f}% used ({system_mem.available / 1024 / 1024 / 1024:.1f}GB free), "
            f"load_avg={os.getloadavg()}"
        )
    except Exception as e:
        resource_info = f"(resource info unavailable: {e})"

    if start_time:
        msg = f"[PERF] {label} - {elapsed:.0f}ms elapsed - {resource_info}"
    else:
        msg = f"[PERF] {label} - {resource_info}"

    # Use print for immediate output in CI logs (logger may be buffered)
    print(msg)  # noqa: T201
    logger.info(msg)

    return current_time


@runtime_checkable
class PlaywrightSetupFunction(Protocol):
    def __call__(self, data: BaseModel, /) -> BaseModel: ...


def create_organization_with_team(data: PlaywrightWorkspaceSetupData) -> PlaywrightWorkspaceSetupResult:
    """Creates PostHog workspace with organization, team, user, API key, and demo data."""
    overall_start = log_timing_and_resources("========== Starting workspace creation ==========")

    org_name = data.organization_name or "Hedgebox Inc."

    # Generate unique email to avoid collisions between parallel tests
    unique_suffix = secrets.token_hex(8)  # 16 character hex string
    user_email = f"test-{unique_suffix}@posthog.com"

    # Use the working generate_demo_data command to create workspace with demo data
    step_start = log_timing_and_resources("Instantiating GenerateDemoDataCommand")
    command = GenerateDemoDataCommand()
    log_timing_and_resources("GenerateDemoDataCommand instantiated", step_start)

    # Determine the reference time for data generation
    fixed_now = datetime(2024, 11, 3, 12, 0, 0)
    if data.use_current_time:
        now = timezone.now()
    else:
        now = fixed_now

    options = {
        "seed": f"playwright_test",  # constant seed
        "now": now,
        "days_past": 30,
        "days_future": 0,
        "n_clusters": 3,  # Reduced from 10 for faster test execution
        "dry_run": False,
        "team_id": None,
        "email": user_email,
        "password": "12345678",
        "product": "hedgebox",
        "staff": False,
        "verbosity": 0,
        "skip_dagster": True,
        "say_on_complete": False,
        "skip_materialization": True,
        "skip_flag_sync": True,
        "skip_user_product_list": True,
    }

    # Call the handle method directly - this creates org, team, user, and demo data
    step_start = log_timing_and_resources("Starting command.handle() - this runs Matrix simulation and saves data")
    command.handle(**options)
    handle_end = log_timing_and_resources("command.handle() completed", step_start)

    handle_duration_ms = (handle_end - step_start) * 1000
    if handle_duration_ms > 30000:
        print(  # noqa: T201
            f"[PERF] WARNING: command.handle() took {handle_duration_ms:.0f}ms (>30s) - "
            "this is the main bottleneck causing test timeouts"
        )

    # Get the created user, organization, and team
    step_start = log_timing_and_resources("Fetching created user from database")
    user = User.objects.get(email=user_email)
    organization = user.organization
    team = user.team
    log_timing_and_resources("User fetched from database", step_start)

    # Update organization name if custom name was provided
    step_start = log_timing_and_resources("Updating organization settings")
    if org_name != "Hedgebox Inc.":
        organization.name = org_name
        organization.save()

    # Bypass billing quota limits so insights always compute on CI
    organization.never_drop_data = True
    # Add advanced permissions feature for password-protected sharing
    organization.available_product_features = [
        {
            "key": AvailableFeature.ADVANCED_PERMISSIONS,
            "name": AvailableFeature.ADVANCED_PERMISSIONS,
        }
    ]
    organization.save()
    log_timing_and_resources("Organization settings updated", step_start)

    # Create personal API key for the user
    step_start = log_timing_and_resources("Creating personal API key")
    api_key_value = f"phx_test_api_key_for_playwright_tests_{unique_suffix}"
    secure_value = hash_key_value(api_key_value)
    mask_value = mask_key_value(api_key_value)
    api_key, _ = PersonalAPIKey.objects.get_or_create(
        user=user,
        label="Test API Key",
        defaults={"secure_value": secure_value, "mask_value": mask_value, "scopes": ["*"]},
    )
    api_key._value = api_key_value  # type: ignore
    log_timing_and_resources("Personal API key created", step_start)

    # Skip all onboarding tasks if requested (prevents Quick Start popover in tests)
    if data.skip_onboarding:
        step_start = log_timing_and_resources("Skipping onboarding tasks")
        # Mark all common onboarding tasks as skipped
        team.onboarding_tasks = {
            "ingest_first_event": "skipped",
            "set_up_reverse_proxy": "skipped",
            "create_first_insight": "skipped",
            "create_first_dashboard": "skipped",
            "track_custom_events": "skipped",
            "define_actions": "skipped",
            "set_up_cohorts": "skipped",
            "explore_trends_insight": "skipped",
            "create_funnel": "skipped",
            "explore_retention_insight": "skipped",
            "explore_paths_insight": "skipped",
            "explore_stickiness_insight": "skipped",
            "explore_lifecycle_insight": "skipped",
            "setup_session_recordings": "skipped",
            "watch_session_recording": "skipped",
        }
        team.save()
        log_timing_and_resources("Onboarding tasks skipped", step_start)

    total_duration_ms = (time.monotonic() - overall_start) * 1000
    log_timing_and_resources(f"========== Workspace creation completed in {total_duration_ms:.0f}ms ==========")

    if total_duration_ms > 30000:
        print(  # noqa: T201
            f"[PERF] CRITICAL: Total workspace creation took {total_duration_ms:.0f}ms (>30s) - "
            "this will likely cause test timeouts (60s limit in beforeAll)"
        )

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
