from __future__ import annotations

from typing import Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from posthog.slack.channels import clip_text
from posthog.slack.formatting import escape_slack_mrkdwn
from posthog.utils import absolute_uri

from products.alerts.backend.logic.insight_alert_destinations import _slack_attachments, _slack_blocks
from products.alerts.backend.logic.insight_alert_message import insight_alert_slack_properties
from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    AnnouncedTransition,
    MessageImage,
    MessageLink,
    SlackMessageContent,
)

# A name reaches the card unescaped, so it is bounded here rather than costing the whole message.
MAX_NAME_CHARS: Final = 150


def _zone(name: str) -> ZoneInfo:
    """The recorded timezone, or UTC.

    `source_detail` crosses Temporal as untyped JSON, and a zone a check recorded can be renamed or
    dropped from the system database before the message goes out.
    """
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def insight_transition_properties(transition: AnnouncedTransition) -> dict[str, Any]:
    detail = transition.source_detail
    breaches = detail.get("breaches") or []
    # Rows come from a stored detail, so their shape is checked rather than assumed. The formatter
    # reads `observed` directly, so a row without it would raise there.
    rows = [row for row in (detail.get("breach_details") or []) if isinstance(row, dict)]
    breach_details = [row for row in rows if row.get("observed")]
    timezone = detail.get("timezone") or "UTC"
    zone = _zone(timezone)
    detected_at = transition.occurred_at.astimezone(zone).strftime("%d %b %Y, %H:%M %Z") + f" ({timezone})"
    affected_dates = detail.get("triggered_dates") or [row["date"] for row in rows if row.get("date")]
    affected_interval = (
        detail.get("interval")
        or next((row["interval"] for row in rows if row.get("interval")), None)
        or detail.get("insight_interval")
    )
    return insight_alert_slack_properties(
        breaches=breaches,
        breach_details=breach_details,
        affected_dates=affected_dates,
        affected_interval=affected_interval,
        project_timezone=zone.key,
        metric_name=detail.get("metric_name") or "Insight",
        is_anomaly=bool(detail.get("is_anomaly")),
        tags=detail.get("tags") or [],
        # Native delivery sends as the check finishes, before any anomaly investigation runs, so it
        # has no summary, verdict or next step to show. The HogFunction path sends later and does.
        summary=None,
        verdict=None,
        investigation_status=None,
        detected_at=detected_at,
        allowed_root=absolute_uri("/"),
    )


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
    properties = insight_transition_properties(transition)
    kind = "Anomaly alert" if properties["slack_alert_type"] == "Anomaly detected" else "Insight alert"
    project_url = project.url if project else absolute_uri(f"/project/{team_id}")
    project_name = project.label if project else transition.source_detail.get("team_name") or ""
    insight_short_id = transition.source_detail.get("insight_short_id")
    name = clip_text(alert_name, MAX_NAME_CHARS)
    fallback = f"{kind} ‘{name}’ triggered"
    blocks = _slack_blocks(
        chart={"type": "image", "image_url": image.url, "alt_text": image.alt_text} if image else {"type": "divider"},
        alert_id=str(alert_id),
        primary_url=alert_url,
        primary_label="🔎 View alert",
        insight_url=absolute_uri(f"/project/{team_id}/insights/{insight_short_id}") if insight_short_id else None,
    )
    attachments = _slack_attachments(
        heading_prefix=f"⚠️ {kind} ‘",
        alert_name=name,
        alert_url=alert_url,
        project_name=clip_text(project_name, MAX_NAME_CHARS) or None,
        project_url=project_url,
        details=properties["slack_alert_details"],
        timing=properties["slack_alert_timing"],
        tags=properties["slack_alert_tags"],
        fallback=fallback,
        blocks=blocks,
    )
    # The card lives in the attachment, but `text` is what Slack reads out in a push notification
    # and what a screen reader announces, so it repeats the fallback rather than going out empty.
    # Escaped, because `text` is mrkdwn and the name is user-written: `<!channel>` would broadcast.
    # The attachment's own fallback and the rich-text elements are not mrkdwn, so they stay literal.
    return SlackMessageContent(text=escape_slack_mrkdwn(fallback), blocks=[], attachments=attachments)
