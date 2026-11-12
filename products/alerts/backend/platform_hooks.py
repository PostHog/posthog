"""The insight hooks the alerts platform calls, registered from `ready()`.

Each hook imports its implementation on its first call. The implementations reach the alert task
helpers, and `ready()` runs in every process, so a module-level import would put them on every
process's startup path.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from products.alerts_platform.backend.facade.contracts import (
        AlertDeliveryRequest,
        AnnouncedTransition,
        EvaluationAnnouncement,
        LegacyEventEmission,
        MessageImage,
        MessageLink,
        SlackMessageContent,
    )


def emit_insight_legacy_events(
    *, request: AlertDeliveryRequest, announcement: EvaluationAnnouncement, emissions: Sequence[LegacyEventEmission]
) -> None:
    from products.alerts.backend import (
        platform_alert_legacy_events,  # noqa: PLC0415 - keeps the alert task helpers off the startup path
    )

    platform_alert_legacy_events.emit_insight_legacy_events(
        request=request, announcement=announcement, emissions=emissions
    )


def insight_chart_image(*, team_id: int, transition: AnnouncedTransition) -> MessageImage | None:
    from products.alerts.backend import (
        platform_alert_legacy_events,  # noqa: PLC0415 - keeps the alert task helpers off the startup path
    )

    return platform_alert_legacy_events.insight_chart_image(team_id=team_id, transition=transition)


def render_insight_slack_message(
    *,
    team_id: int,
    transition: AnnouncedTransition,
    alert_name: str,
    alert_url: str,
    project: MessageLink | None,
    image: MessageImage | None,
) -> SlackMessageContent | None:
    from products.alerts.backend import platform_alert_slack  # noqa: PLC0415 - keeps alert models off the startup path

    return platform_alert_slack.render_insight_slack_message(
        team_id=team_id, transition=transition, alert_name=alert_name, alert_url=alert_url, project=project, image=image
    )


def insight_alert_creator(*, team_id: int, alert_id: UUID) -> int | None:
    from products.alerts.backend.models.alert import (
        AlertConfiguration,  # noqa: PLC0415 - keeps alert models off the startup path
    )
    from products.alerts.backend.platform_insight_alert import native_insight_alert_view  # noqa: PLC0415

    row = AlertConfiguration.objects.filter(team_id=team_id, id=alert_id).values("created_by_id").first()
    if row is not None:
        return row["created_by_id"]
    native = native_insight_alert_view(team_id, alert_id)
    return native.created_by_id if native is not None else None


def insight_alert_viewer(*, team_id: int, alert_id: UUID, user_id: int) -> bool:
    from posthog.models import User  # noqa: PLC0415 - keeps models off the startup path

    from products.alerts.backend.logic.alert_email import can_view_insight  # noqa: PLC0415
    from products.alerts.backend.models.alert import AlertConfiguration  # noqa: PLC0415
    from products.alerts.backend.platform_insight_alert import native_insight_alert_view  # noqa: PLC0415

    alert = AlertConfiguration.objects.filter(team_id=team_id, id=alert_id).select_related("team", "insight").first()
    if alert is None and (native := native_insight_alert_view(team_id, alert_id)) is not None:
        alert = AlertConfiguration.from_platform_view(native, team_id=team_id)
    user = User.objects.filter(id=user_id).first() if alert is not None else None
    return alert is not None and user is not None and can_view_insight(user, alert)


def subscribers_with_insight_access(*, team_id: int, configuration_id: UUID, user_ids: Collection[int]) -> list[int]:
    from products.alerts.backend import (
        platform_insight_alert,  # noqa: PLC0415 - keeps the alert task helpers off the startup path
    )

    return platform_insight_alert.subscribers_with_insight_access(
        team_id=team_id, configuration_id=configuration_id, user_ids=user_ids
    )
