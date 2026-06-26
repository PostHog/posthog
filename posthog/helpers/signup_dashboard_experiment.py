from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import posthoganalytics

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_templates import DashboardTemplate

if TYPE_CHECKING:
    from posthog.models.team.team import Team

STARTER_DASHBOARD_EXPERIMENT_FLAG_KEY = "starter-dashboard-v2"

StarterDashboardVariant = Literal["control", "test"]


def get_starter_dashboard_variant(team: Team) -> StarterDashboardVariant:
    """Resolve experiment arm for a newly created non-demo project."""
    try:
        flag_result = posthoganalytics.get_feature_flag(
            STARTER_DASHBOARD_EXPERIMENT_FLAG_KEY,
            str(team.uuid),
            groups={"organization": str(team.organization_id)},
        )
    except Exception:
        return "control"

    # get_feature_flag is typed as FeatureFlag | None but returns the variant key string at
    # runtime; normalise to str so the comparison is well-typed.
    return "test" if str(flag_result) == "test" else "control"


def get_signup_dashboard_template(variant: StarterDashboardVariant) -> DashboardTemplate:
    if variant == "test":
        return DashboardTemplate.default_signup_template()
    return DashboardTemplate.legacy_signup_template()


def get_signup_dashboard_name(variant: StarterDashboardVariant) -> str:
    return "Your starter dashboard" if variant == "test" else "My App Dashboard"


def create_signup_primary_dashboard(team: Team, *, using: str | None = None) -> Dashboard:
    from posthog.helpers.dashboard_templates import create_from_template  # noqa: PLC0415 — breaks team import cycle

    variant = get_starter_dashboard_variant(team)
    template = get_signup_dashboard_template(variant)

    dashboard = Dashboard.objects.db_manager(using).create(
        name=get_signup_dashboard_name(variant),
        pinned=True,
        team=team,
        description=template.dashboard_description or "",
    )
    create_from_template(dashboard, template)

    if team.extra_settings is None:
        team.extra_settings = {}
    team.extra_settings["starter_dashboard_variant"] = variant

    report_starter_dashboard_exposure(team, variant)
    return dashboard


def report_starter_dashboard_exposure(team: Team, variant: StarterDashboardVariant) -> None:
    from posthog.event_usage import report_team_action  # noqa: PLC0415 — breaks team import cycle

    # Project-scoped assignment: distinct_id is the environment UUID so each new project
    # gets a stable arm independent of which user created it.
    report_team_action(
        team,
        "$feature_flag_called",
        properties={
            "$feature_flag": STARTER_DASHBOARD_EXPERIMENT_FLAG_KEY,
            "$feature_flag_response": variant,
            "starter_dashboard_variant": variant,
        },
        group_properties={
            "starter_dashboard_variant": variant,
            "starter_dashboard_experiment": STARTER_DASHBOARD_EXPERIMENT_FLAG_KEY,
        },
    )
