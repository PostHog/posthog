"""Playwright setup functions for test data creation."""

import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from django.utils import timezone

from pydantic import BaseModel

from posthog.constants import AvailableFeature
from posthog.management.commands.generate_demo_data import Command as GenerateDemoDataCommand
from posthog.models import Dashboard, DashboardTile, Insight, PersonalAPIKey, Team, User
from posthog.models.insight_variable import InsightVariable
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import mask_key_value


class PlaywrightSetupVariableType(StrEnum):
    STRING = "String"
    NUMBER = "Number"
    BOOLEAN = "Boolean"
    LIST = "List"
    DATE = "Date"


class PlaywrightSetupVariable(BaseModel):
    name: str
    type: PlaywrightSetupVariableType
    default_value: Any | None = None


class PlaywrightSetupInsight(BaseModel):
    name: str
    query: dict[str, Any]
    variable_indexes: list[int] | None = None


class PlaywrightSetupDashboard(BaseModel):
    name: str
    insight_indexes: list[int] | None = None
    filters: dict[str, Any] | None = None
    variable_overrides: dict[str, Any] | None = None


class PlaywrightSetupEvent(BaseModel):
    event: str
    distinct_id: str
    timestamp: str
    properties: dict[str, Any] | None = None


class PlaywrightWorkspaceSetupData(BaseModel):
    organization_name: str | None = None
    use_current_time: bool | None = None
    skip_onboarding: bool | None = None
    no_demo_data: bool | None = None
    insight_variables: list[PlaywrightSetupVariable] | None = None
    insights: list[PlaywrightSetupInsight] | None = None
    dashboards: list[PlaywrightSetupDashboard] | None = None
    events: list[PlaywrightSetupEvent] | None = None


class PlaywrightSetupCreatedVariable(BaseModel):
    id: str
    code_name: str


class PlaywrightSetupCreatedInsight(BaseModel):
    id: int
    short_id: str


class PlaywrightSetupCreatedDashboard(BaseModel):
    id: int


class PlaywrightWorkspaceSetupResult(BaseModel):
    organization_id: str
    team_id: str
    organization_name: str
    team_name: str
    user_id: str
    user_email: str
    personal_api_key: str
    created_variables: list[PlaywrightSetupCreatedVariable] | None = None
    created_insights: list[PlaywrightSetupCreatedInsight] | None = None
    created_dashboards: list[PlaywrightSetupCreatedDashboard] | None = None


@runtime_checkable
class PlaywrightSetupFunction(Protocol):
    def __call__(self, data: BaseModel, /) -> BaseModel: ...


def create_organization_with_team(
    data: PlaywrightWorkspaceSetupData,
) -> PlaywrightWorkspaceSetupResult:
    """Creates PostHog workspace with organization, team, user, API key, and optionally demo data."""
    org_name = data.organization_name or "Hedgebox Inc."

    # Generate unique email to avoid collisions between parallel tests
    unique_suffix = secrets.token_hex(8)  # 16 character hex string
    user_email = f"test-{unique_suffix}@posthog.com"
    user_password = "12345678"

    if data.no_demo_data:
        from posthog.models.organization import Organization
        from posthog.models.project import Project

        organization = Organization.objects.create(name=org_name)
        project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=organization)
        team = Team.objects.create(
            id=project.id,
            project=project,
            organization=organization,
            has_completed_onboarding_for={"product_analytics": True},
        )
        user = User.objects.create_and_join(organization, user_email, user_password)
    else:
        command = GenerateDemoDataCommand()

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
            "password": user_password,
            "product": "hedgebox",
            "staff": False,
            "verbosity": 0,
            "skip_dagster": True,
            "say_on_complete": False,
            "skip_materialization": True,
            "skip_flag_sync": True,
            "skip_user_product_list": True,
        }

        command.handle(**options)

        user = User.objects.get(email=user_email)
        organization = user.organization
        team = user.team

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

    # Create personal API key for the user
    api_key_value = f"phx_test_api_key_for_playwright_tests_{unique_suffix}"
    secure_value = hash_key_value(api_key_value)
    mask_value = mask_key_value(api_key_value)
    api_key, _ = PersonalAPIKey.objects.get_or_create(
        user=user,
        label="Test API Key",
        defaults={
            "secure_value": secure_value,
            "mask_value": mask_value,
            "scopes": ["*"],
        },
    )
    api_key._value = api_key_value  # type: ignore

    # Skip all onboarding tasks if requested (prevents Quick Start popover in tests)
    if data.skip_onboarding:
        team.onboarding_tasks = {
            "ingest_first_event": "completed",
            "set_up_reverse_proxy": "completed",
            "create_first_insight": "completed",
            "create_first_dashboard": "completed",
            "track_custom_events": "completed",
            "define_actions": "completed",
            "set_up_cohorts": "completed",
            "explore_trends_insight": "completed",
            "create_funnel": "completed",
            "explore_retention_insight": "completed",
            "explore_paths_insight": "completed",
            "explore_stickiness_insight": "completed",
            "explore_lifecycle_insight": "completed",
            "setup_session_recordings": "completed",
            "watch_session_recording": "completed",
        }
        team.save()

    created_variables = _create_variables(data, team)
    created_insights = _create_insights(data, team, user, created_variables)
    created_dashboards = _create_dashboards(data, team, user, created_variables, created_insights)
    _create_events_and_persons(data, team)

    return PlaywrightWorkspaceSetupResult(
        organization_id=str(organization.id),
        team_id=str(team.id),
        organization_name=organization.name,
        team_name=team.name,
        user_id=str(user.id),
        user_email=user.email,
        personal_api_key=api_key._value,  # type: ignore
        created_variables=(
            [PlaywrightSetupCreatedVariable(id=str(v.id), code_name=v.code_name or "") for v in created_variables]
            if created_variables
            else None
        ),
        created_insights=(
            [PlaywrightSetupCreatedInsight(id=i.id, short_id=i.short_id) for i in created_insights]
            if created_insights
            else None
        ),
        created_dashboards=(
            [PlaywrightSetupCreatedDashboard(id=d.id) for d in created_dashboards] if created_dashboards else None
        ),
    )


def _derive_code_name(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c == " " or c == "_").replace(" ", "_").lower()


def _create_variables(data: PlaywrightWorkspaceSetupData, team: Team) -> list[InsightVariable]:
    if not data.insight_variables:
        return []
    created: list[InsightVariable] = []
    for var_spec in data.insight_variables:
        var = InsightVariable.objects.create(
            team=team,
            name=var_spec.name,
            code_name=_derive_code_name(var_spec.name),
            type=var_spec.type,
            default_value=var_spec.default_value,
        )
        created.append(var)
    return created


def _create_insights(
    data: PlaywrightWorkspaceSetupData,
    team: Team,
    user: User,
    created_variables: list[InsightVariable],
) -> list[Insight]:
    if not data.insights:
        return []
    created: list[Insight] = []
    for insight_spec in data.insights:
        query = insight_spec.query
        if insight_spec.variable_indexes and created_variables:
            variables_dict: dict[str, dict[str, str]] = {}
            for idx in insight_spec.variable_indexes:
                var = created_variables[int(idx)]
                variables_dict[str(var.id)] = {
                    "code_name": var.code_name or "",
                    "variableId": str(var.id),
                }
            if "source" in query:
                query = {
                    **query,
                    "source": {**query["source"], "variables": variables_dict},
                }
        insight = Insight.objects.create(
            team=team,
            name=insight_spec.name,
            query=query,
            created_by=user,
        )
        created.append(insight)
    return created


def _create_dashboards(
    data: PlaywrightWorkspaceSetupData,
    team: Team,
    user: User,
    created_variables: list[InsightVariable],
    created_insights: list[Insight],
) -> list[Dashboard]:
    if not data.dashboards:
        return []
    created: list[Dashboard] = []
    for dash_spec in data.dashboards:
        variables = None
        if dash_spec.variable_overrides and created_variables:
            variables = {}
            for idx_str, override_value in dash_spec.variable_overrides.items():
                var = created_variables[int(idx_str)]
                variables[str(var.id)] = {
                    "code_name": var.code_name or "",
                    "variableId": str(var.id),
                    "value": override_value,
                }
        dashboard = Dashboard.objects.create(
            team=team,
            name=dash_spec.name,
            created_by=user,
            filters=dash_spec.filters or {},
            variables=variables or {},
        )
        if dash_spec.insight_indexes and created_insights:
            for idx in dash_spec.insight_indexes:
                if int(idx) >= len(created_insights):
                    continue  # Skip invalid indexes
                DashboardTile.objects.create(
                    dashboard=dashboard,
                    insight=created_insights[int(idx)],
                )
        created.append(dashboard)
    return created


def _count_events_in_clickhouse(team_id: int) -> int:
    from posthog.clickhouse.client import sync_execute

    result = sync_execute(
        "SELECT count() FROM events WHERE team_id = %(team_id)s",
        {"team_id": team_id},
    )
    return int(result[0][0])


def _wait_for_events_in_clickhouse(team_id: int, expected_count: int, timeout_seconds: int = 10) -> None:
    """Poll ClickHouse until the expected number of events appear, or timeout."""
    import time

    deadline = time.monotonic() + timeout_seconds
    count = 0
    while time.monotonic() < deadline:
        count = _count_events_in_clickhouse(team_id)
        if count >= expected_count:
            return
        time.sleep(0.5)
    raise TimeoutError(
        f"Expected {expected_count} events in ClickHouse for team {team_id}, "
        f"but only found {count} after {timeout_seconds}s"
    )


def _create_events_and_persons(data: PlaywrightWorkspaceSetupData, team: Team) -> None:
    if not data.events:
        return

    import uuid as uuid_module

    from posthog.models import Person, PersonDistinctId
    from posthog.models.event.util import create_event
    from posthog.models.person.util import create_person, create_person_distinct_id
    from posthog.models.utils import UUIDT

    # Derive persons from distinct_ids in events
    distinct_ids = {e.distinct_id for e in data.events}
    person_uuids: dict[str, str] = {}
    for distinct_id in distinct_ids:
        person_uuid = str(UUIDT())
        person_uuids[distinct_id] = person_uuid
        create_person(team_id=team.pk, version=0, uuid=person_uuid)
        create_person_distinct_id(team_id=team.pk, distinct_id=distinct_id, person_id=person_uuid)
        pg_person = Person.objects.create(team=team, uuid=person_uuid)
        PersonDistinctId.objects.create(team=team, person=pg_person, distinct_id=distinct_id)

    # Register event and property definitions so the taxonomic filter works
    from products.event_definitions.backend.models.event_definition import EventDefinition
    from products.event_definitions.backend.models.property_definition import PropertyDefinition

    event_names = {e.event for e in data.events}
    for event_name in event_names:
        EventDefinition.objects.get_or_create(team=team, name=event_name, defaults={"project_id": team.project_id})

    property_names: set[str] = set()
    for e in data.events:
        if e.properties:
            property_names.update(e.properties.keys())
    for prop_name in property_names:
        PropertyDefinition.objects.get_or_create(
            team=team,
            name=prop_name,
            type=PropertyDefinition.Type.EVENT,
            defaults={"project_id": team.project_id},
        )

    baseline_count = _count_events_in_clickhouse(team.pk)

    for event_spec in data.events:
        ts = datetime.fromisoformat(event_spec.timestamp.replace("Z", "+00:00"))
        create_event(
            event_uuid=UUIDT(unix_time_ms=int(ts.timestamp() * 1000)),
            event=event_spec.event,
            distinct_id=event_spec.distinct_id,
            team=team,
            timestamp=ts,
            properties=event_spec.properties or {},
            person_id=uuid_module.UUID(person_uuids[event_spec.distinct_id]),
        )

    _wait_for_events_in_clickhouse(team.pk, baseline_count + len(data.events))


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
