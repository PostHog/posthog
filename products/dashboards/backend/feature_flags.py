from __future__ import annotations

from typing import TYPE_CHECKING

import posthoganalytics

from posthog.permissions import _FORCE_ENABLED_FLAGS, posthog_feature_flag_enabled

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

DASHBOARD_V2_FLAG = "dashboard-v2"


def widget_flag_enabled(flag: str, *, team: Team, user: User | None = None) -> bool:
    """Match the existing in-app widget flag evaluation."""
    if flag in _FORCE_ENABLED_FLAGS:
        return True

    distinct_id = (user.distinct_id or str(user.uuid)) if user is not None else str(team.uuid)
    organization_id = str(team.organization_id)
    project_id = str(team.id)

    return bool(
        posthoganalytics.feature_enabled(
            flag,
            distinct_id,
            groups={"organization": organization_id, "project": project_id},
            group_properties={"organization": {"id": organization_id}, "project": {"id": project_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )


def dashboard_v2_enabled(team: Team, user: User | None = None) -> bool:
    """`dashboard-v2` is aggregated by project, so the browser, API and background jobs agree on it."""
    distinct_id = str(user.distinct_id) if user is not None and user.distinct_id else str(team.uuid)
    return posthog_feature_flag_enabled(
        DASHBOARD_V2_FLAG,
        distinct_id,
        organization_id=team.organization_id,
        team_id=team.pk,
        only_evaluate_locally=True,
    )
