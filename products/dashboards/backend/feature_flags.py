from __future__ import annotations

from typing import TYPE_CHECKING

import posthoganalytics

from posthog.permissions import _FORCE_ENABLED_FLAGS

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

DASHBOARD_WIDGETS_FLAG = "dashboard-widgets"
DASHBOARD_CUSTOMIZATION_FLAG = "dashboard-customization"
DASHBOARD_SAVED_VIEWS_FLAG = "dashboard-saved-views"


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


def dashboard_widgets_enabled(*, team: Team, user: User | None = None) -> bool:
    return widget_flag_enabled(DASHBOARD_WIDGETS_FLAG, team=team, user=user)


def dashboard_customization_enabled(*, team: Team, user: User | None = None) -> bool:
    return widget_flag_enabled(DASHBOARD_CUSTOMIZATION_FLAG, team=team, user=user)


def dashboard_saved_views_enabled(*, team: Team) -> bool:
    return widget_flag_enabled(DASHBOARD_SAVED_VIEWS_FLAG, team=team)
