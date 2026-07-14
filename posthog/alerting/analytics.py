from typing import TYPE_CHECKING, Literal

from django.contrib.auth.models import AnonymousUser

from posthog.event_usage import AnalyticsProps, report_user_action
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.synthetic_user import SyntheticUser

if TYPE_CHECKING:
    from rest_framework.request import Request

AlertAction = Literal["created", "updated", "deleted"]


def report_alert_action(
    *,
    user: User | AnonymousUser | SyntheticUser,
    action: AlertAction,
    config_type: str,
    alert_id: str,
    alert_name: str,
    properties: dict[str, object] | None = None,
    team: Team | None = None,
    request: "Request | None" = None,
    analytics_props: AnalyticsProps | None = None,
) -> None:
    report_user_action(
        user,
        f"alert {action}",
        {
            **(properties or {}),
            "alert_id": alert_id,
            "alert_name": alert_name,
            "config_type": config_type,
        },
        team=team,
        request=request,
        analytics_props=analytics_props,
    )
