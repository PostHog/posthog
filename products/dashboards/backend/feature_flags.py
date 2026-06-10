from __future__ import annotations

from typing import TYPE_CHECKING

import posthoganalytics

from posthog.permissions import _FORCE_ENABLED_FLAGS

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

DASHBOARD_WIDGETS_FLAG = "dashboard-widgets"


def dashboard_widgets_enabled(*, team: Team, user: User | None = None) -> bool:
    """Match in-app flag evaluation: user distinct_id plus project/org groups."""
    if DASHBOARD_WIDGETS_FLAG in _FORCE_ENABLED_FLAGS:
        return True

    distinct_id = (user.distinct_id or str(user.uuid)) if user is not None else str(team.uuid)
    organization_id = str(team.organization_id)
    project_id = str(team.id)

    return bool(
        posthoganalytics.feature_enabled(
            DASHBOARD_WIDGETS_FLAG,
            distinct_id,
            groups={"organization": organization_id, "project": project_id},
            group_properties={"organization": {"id": organization_id}, "project": {"id": project_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )
