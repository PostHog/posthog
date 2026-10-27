from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from posthog.slack.formatting import escape_slack_mrkdwn
from posthog.slack.markdown import slack_rich_text

_VERDICTS = {
    "true_positive": "Unusual change confirmed",
    "false_positive": "Expected behavior",
    "inconclusive": "Investigation inconclusive",
}
_TIME_OR_VALUE = re.compile(
    r"(?P<time>\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?\b|\b\d{1,2}:\d{2}(?::\d{2})?\b)"
    r"|(?P<value>(?<![\w])[-+~]?\d+(?:[.,]\d+)*(?:\s?(?:ms|seconds?|minutes?|hours?|days?|%|s))?(?!\w))"
)


def _breach_elements(text: str, metric_name: str) -> list[dict[str, Any]]:
    pattern = _TIME_OR_VALUE
    if metric_name:
        pattern = re.compile(f"(?P<metric>{re.escape(metric_name)})|{_TIME_OR_VALUE.pattern}")
    elements: list[dict[str, Any]] = []
    cursor = 0
    for match in pattern.finditer(text):
        if match.start() > cursor:
            elements.append({"type": "text", "text": text[cursor : match.start()]})
        style = {"code": True}
        if match.lastgroup == "time":
            style = {"italic": True}
        elements.append({"type": "text", "text": match.group(), "style": style})
        cursor = match.end()
    if cursor < len(text):
        elements.append({"type": "text", "text": text[cursor:]})
    return elements


_INTERVAL_DELTAS = {
    "second": relativedelta(seconds=1),
    "minute": relativedelta(minutes=1),
    "hour": relativedelta(hours=1),
    "day": relativedelta(days=1),
    "week": relativedelta(weeks=1),
    "month": relativedelta(months=1),
    "quarter": relativedelta(months=3),
    "year": relativedelta(years=1),
}


def _affected_period(dates: list[str], project_timezone: str, interval: str | None) -> str:
    labels: list[str] = []
    endpoints = [dates[0], dates[-1]]
    delta = _INTERVAL_DELTAS.get(interval or "")
    if delta is not None:
        try:
            end = datetime.fromisoformat(dates[-1])
            if end.tzinfo is None and interval in {"second", "minute", "hour"}:
                end = end.replace(tzinfo=ZoneInfo(project_timezone))
            if end.tzinfo is not None:
                end = end.astimezone(ZoneInfo(project_timezone))
            if interval in {"second", "minute", "hour"} and end.tzinfo is not None:
                end = end.astimezone(UTC) + delta
            else:
                end += delta
            endpoints[-1] = end.isoformat()
        except ValueError:
            pass
    timezone = ZoneInfo(project_timezone)
    offsets = set()
    for value in endpoints:
        try:
            point = datetime.fromisoformat(value)
        except ValueError:
            continue
        if point.tzinfo is not None:
            offsets.add(point.astimezone(timezone).utcoffset())
    show_zone = len(offsets) > 1
    for value in dict.fromkeys(endpoints):
        try:
            point = datetime.fromisoformat(value)
        except ValueError:
            labels.append(value[:100])
            continue
        if point.tzinfo is not None:
            point = point.astimezone(ZoneInfo(project_timezone))
        label = point.strftime("%d %b %Y")
        if len(value) > 10:
            time_format = "%d %b %Y, %H:%M:%S" if interval == "second" else "%d %b %Y, %H:%M"
            if show_zone:
                time_format += " %Z"
            label = point.strftime(time_format)
        labels.append(label)
    return " to ".join(labels) + f" ({project_timezone})"


def insight_alert_slack_properties(
    *,
    breaches: list[str],
    metric_name: str,
    is_anomaly: bool = False,
    tags: list[str] | None = None,
    breach_details: list[dict[str, str]] | None = None,
    affected_dates: list[str] | None = None,
    affected_interval: str | None = None,
    project_timezone: str = "UTC",
    metric_description: str | None = None,
    next_step: str | None = None,
    summary: str | None,
    verdict: str | None,
    investigation_status: str | None,
    detected_at: str,
    allowed_root: str,
) -> dict[str, Any]:
    investigation = _VERDICTS.get(verdict or "", "")
    if investigation_status in {"pending", "running"}:
        investigation = "In progress"
    elif investigation_status == "failed":
        investigation = "Incomplete"
    content: dict[str, Any]
    if breach_details and not summary:
        sections: list[dict[str, Any]] = []
        for detail in breach_details[:5]:
            elements: list[dict[str, Any]] = []
            if detail.get("group"):
                elements.extend(
                    [
                        {"type": "text", "text": detail["group"][:400], "style": {"code": True}},
                        {"type": "text", "text": ": "},
                    ]
                )
            elements.extend(
                [
                    {"type": "text", "text": "Reached "},
                    {"type": "text", "text": detail["observed"][:400], "style": {"code": True}},
                ]
            )
            if detail.get("limit"):
                label = detail.get("limit_label", "Limit").lower()
                if detail.get("change"):
                    elements.extend(
                        [
                            {"type": "text", "text": " ("},
                            {"type": "text", "text": detail["change"][:400], "style": {"code": True}},
                            {"type": "text", "text": "), beyond the change limit of "},
                        ]
                    )
                else:
                    elements.append({"type": "text", "text": ", beyond the " + label + " of "})
                elements.append({"type": "text", "text": detail["limit"][:400], "style": {"code": True}})
            elements.append({"type": "text", "text": "."})
            if detail.get("previous"):
                elements.extend(
                    [
                        {"type": "text", "text": "\nPrevious interval: "},
                        {"type": "text", "text": detail["previous"][:400], "style": {"code": True}},
                        {"type": "text", "text": "."},
                    ]
                )
            sections.append({"type": "rich_text_section", "elements": elements})
            if detail.get("other_groups"):
                sections.append(
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {
                                "type": "text",
                                "text": f"{detail['other_groups']} more affected groups. Open the insight for details.",
                            }
                        ],
                    }
                )
        content = {"type": "rich_text", "elements": sections}
    elif summary and summary.strip():
        if len(summary) > 2800:
            summary = summary[:2797] + "..."
        content = slack_rich_text(summary, allowed_root=allowed_root)
    else:
        sections = []
        budget = 2600
        for breach in breaches:
            if not breach.strip():
                continue
            if budget < 100 or len(sections) == 10:
                break
            text = breach
            if len(text) > budget:
                text = text[: budget - 3] + "..."
            sections.append({"type": "rich_text_section", "elements": _breach_elements(text, metric_name)})
            budget -= len(text)
        if not sections:
            sections.append(
                {
                    "type": "rich_text_section",
                    "elements": [{"type": "text", "text": "Alert fired. Open the insight for details."}],
                }
            )
        content = {
            "type": "rich_text",
            "elements": [{"type": "rich_text_list", "style": "bullet", "elements": sections}],
        }
        omitted = max(0, sum(bool(breach.strip()) for breach in breaches) - len(sections))
        if omitted:
            content["elements"].append(
                {
                    "type": "rich_text_section",
                    "elements": [{"type": "text", "text": f"{omitted} more breaches. Open the insight for details."}],
                }
            )
    timing: dict[str, Any] = {"type": "divider"}
    if affected_dates:
        label = "📅 Affected period" if affected_interval in _INTERVAL_DELTAS else "📅 Affected data points"
        period = escape_slack_mrkdwn(_affected_period(affected_dates, project_timezone, affected_interval))
        timing = {"type": "section", "text": {"type": "mrkdwn", "text": f"*{label}*\n_{period}_"}}
    child_blocks: list[dict[str, Any]] = []
    if metric_description:
        child_blocks.append(
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {"type": "text", "text": "Measures: ", "style": {"bold": True}},
                            {"type": "text", "text": metric_description[:400]},
                        ],
                    }
                ],
            }
        )
    child_blocks.append(content)
    if investigation:
        child_blocks.append(
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {"type": "text", "text": "Investigation: ", "style": {"bold": True}},
                            {"type": "text", "text": investigation},
                        ],
                    }
                ],
            }
        )
    if next_step:
        child_blocks.append(slack_rich_text("**Next check:** " + next_step[:500], allowed_root=allowed_root))
    tag_elements: list[dict[str, Any]] = [{"type": "text", "text": "Insight tags: ", "style": {"bold": True}}]
    for tag in (tags or [])[:10]:
        if len(tag_elements) > 1:
            tag_elements.append({"type": "text", "text": " "})
        tag_elements.append({"type": "text", "text": tag[:255], "style": {"code": True}})
    tag_block: dict[str, Any] = {"type": "divider"}
    if tags:
        tag_block = {"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": tag_elements}]}
    return {
        "slack_alert_tags": tag_block,
        "slack_alert_type": "Anomaly detected" if is_anomaly else "Limit crossed",
        "slack_alert_status": "Triggered",
        "slack_alert_timing": timing,
        "slack_alert_detected_at": detected_at,
        "slack_alert_details": {
            "type": "rich_text",
            "elements": [element for block in child_blocks for element in block["elements"]],
        },
    }
