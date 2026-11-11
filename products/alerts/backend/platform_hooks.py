"""The insight hooks the alerts platform calls, registered from `ready()`.

Each hook imports its implementation on its first call. The implementations reach the alert task
helpers, and `ready()` runs in every process, so a module-level import would put them on every
process's startup path.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
