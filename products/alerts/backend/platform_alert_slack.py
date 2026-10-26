from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

from posthog.schema_enums import AlertState
from posthog.utils import absolute_uri

from products.alerts.backend.logic.insight_alert_destinations import _slack_attachments, _slack_blocks
from products.alerts.backend.logic.insight_alert_message import insight_alert_slack_properties
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    AnnouncedTransition,
    MessageImage,
    MessageLink,
    SlackMessageContent,
)


def insight_transition_properties(alert: AlertConfiguration, transition: AnnouncedTransition) -> dict[str, Any]:
    detail = transition.source_detail
    breaches = detail.get("breaches") or []
    detected_at = (
        transition.occurred_at.astimezone(ZoneInfo(alert.team.timezone)).strftime("%d %b %Y, %H:%M %Z")
        + f" ({alert.team.timezone})"
    )
    insight_query = alert.insight.query or {}
    insight_source = insight_query.get("source") or insight_query
    affected_interval = next(
        (row["interval"] for row in detail.get("breach_details", []) if row.get("interval")),
        insight_source.get("interval"),
    )
    properties: dict[str, Any] = {
        **alert.internal_event_properties(state=AlertState.FIRING.value, last_checked_at=transition.occurred_at),
        "breaches": "\n".join(breaches),
        **insight_alert_slack_properties(
            breaches=breaches,
            breach_details=detail.get("breach_details"),
            affected_dates=[row["date"] for row in detail.get("breach_details", []) if row.get("date")],
            affected_interval=affected_interval,
            project_timezone=alert.team.timezone,
            metric_name=alert.insight.name or alert.insight.derived_name or "Insight",
            is_anomaly=bool(alert.detector_config),
            tags=list(
                alert.insight.tagged_items.filter(tag__team_id=alert.team_id)
                .values_list("tag__name", flat=True)
                .order_by("tag__name")[:10]
            ),
            summary=None,
            verdict=None,
            investigation_status=None,
            detected_at=detected_at,
            allowed_root=absolute_uri("/"),
        ),
    }
    return properties


def render_insight_slack_message(
    *,
    team_id: int,
    transition: AnnouncedTransition,
    alert_name: str,
    alert_url: str,
    project: MessageLink | None,
    image: MessageImage | None,
) -> SlackMessageContent | None:
    if transition.kind != AlertEventKind.FIRING:
        return None
    alert_id = transition.source_detail.get("alert_id")
    if not alert_id:
        return None
    alert = AlertConfiguration.objects.select_related("team", "insight").filter(team_id=team_id, id=alert_id).first()
    if alert is None:
        return None
    properties = insight_transition_properties(alert, transition)
    kind = "Anomaly alert" if properties["slack_alert_type"] == "Anomaly detected" else "Insight alert"
    project_url = project.url if project else absolute_uri(f"/project/{team_id}")
    insight_short_id = transition.source_detail.get("insight_short_id") or alert.insight.short_id
    insight_url = absolute_uri(f"/project/{team_id}/insights/{insight_short_id}")
    blocks = _slack_blocks(
        chart={"type": "image", "image_url": image.url, "alt_text": image.alt_text} if image else {"type": "divider"},
        alert_id=str(alert_id),
        primary_url=alert_url,
        primary_label="🔎 View alert",
        insight_url=insight_url,
    )
    attachments = _slack_attachments(
        heading_prefix=f"⚠️ {kind} ‘",
        alert_name=alert_name,
        alert_url=alert_url,
        project_name=project.label if project else alert.team.name,
        project_url=project_url,
        details=properties["slack_alert_details"],
        timing=properties["slack_alert_timing"],
        tags=properties["slack_alert_tags"],
        fallback=f"{kind} ‘{alert_name}’ triggered",
        blocks=blocks,
    )
    return SlackMessageContent(text="", blocks=[], attachments=attachments)
