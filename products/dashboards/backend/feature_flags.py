from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

from posthog.api.services.flags_service import get_flags_from_service
from posthog.permissions import _FORCE_ENABLED_FLAGS

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

DASHBOARD_WIDGETS_FLAG = "dashboard-widgets"
DASHBOARD_CUSTOMIZATION_FLAG = "dashboard-customization"


def widget_flag_enabled(flag: str, *, team: Team, user: User | None = None) -> bool:
    """Match in-app flag evaluation: user distinct_id plus project/org groups."""
    if flag in _FORCE_ENABLED_FLAGS:
        return True

    distinct_id = (user.distinct_id or str(user.uuid)) if user is not None else str(team.uuid)
    organization_id = str(team.organization_id)
    project_id = str(team.id)

    try:
        # Cohort targeting needs the remote evaluator; process-local definitions do not include membership.
        result = get_flags_from_service(
            team.api_token,
            distinct_id,
            groups={"organization": organization_id, "project": project_id},
            flag_keys=[flag],
            internal_request_token=settings.INTERNAL_REQUEST_TOKEN,
            evaluation_runtime="all",
        )
    except Exception:
        return False
    return bool(result.get("flags", {}).get(flag, {}).get("enabled"))


def dashboard_widgets_enabled(*, team: Team, user: User | None = None) -> bool:
    return widget_flag_enabled(DASHBOARD_WIDGETS_FLAG, team=team, user=user)


def dashboard_customization_enabled(*, team: Team, user: User | None = None) -> bool:
    return widget_flag_enabled(DASHBOARD_CUSTOMIZATION_FLAG, team=team, user=user)
