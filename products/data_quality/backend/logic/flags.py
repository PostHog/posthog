from typing import TYPE_CHECKING

from django.conf import settings

import posthoganalytics

if TYPE_CHECKING:
    from posthog.models.team import Team

DATA_QUALITY_CHECKS_FEATURE_FLAG = "data-quality-checks"


def is_data_quality_checks_enabled(team: "Team") -> bool:
    """The `data-quality-checks` flag check, org-keyed. Canonical home for the check -- gate any
    data-quality surface (API, information_schema tables, MCP tools, triggers) through here."""
    return _get_data_quality_checks_flag(team) is True


def _get_data_quality_checks_flag(team: "Team") -> bool | None:
    # The flag is evaluated against PostHog's own analytics project, which a local or end-to-end
    # environment has no membership in, so it would gate the whole product out of both.
    if settings.DEBUG or settings.E2E_TESTING:
        return True
    return posthoganalytics.feature_enabled(
        DATA_QUALITY_CHECKS_FEATURE_FLAG,
        str(team.organization_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def is_data_quality_checks_enabled_for_team_id(team_id: int) -> bool:
    """Flag check for callers that only hold a team id (trigger gates, activities)."""
    return get_data_quality_checks_flag_for_team_id(team_id) is True


def get_data_quality_checks_flag_for_team_id(team_id: int) -> bool | None:
    from posthog.models.team import Team  # noqa: PLC0415 — the app registry is not ready at import time

    team = Team.objects.filter(id=team_id).only("id", "organization_id").first()
    if team is None:
        return False
    return _get_data_quality_checks_flag(team)
