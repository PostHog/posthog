"""Delivery logic for evaluation reports (email and Slack)."""

import re
from datetime import UTC, datetime

import structlog
from markdown_it import MarkdownIt
from markdown_to_mrkdwn import SlackMarkdownConverter

from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import REPORT_SECTIONS, EvalReportContent

logger = structlog.get_logger(__name__)

UUID_LINK_PATTERN = re.compile(r"`([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})`")

# Matches a leading markdown heading line at the very start of a section's content.
# The renderer (email/Slack/UI) already emits its own section title, so if the agent
# also started the section with its own `## Executive summary` heading we strip it
# to avoid duplicated titles. See EvaluationReportViewer.tsx for the parallel fix.
_LEADING_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*(?:\r?\n|$)")

SECTION_TITLES = {
    "executive_summary": "Executive Summary",
    "statistics": "Statistics",
    "trend_analysis": "Trend Analysis",
    "failure_patterns": "Failure Patterns",
    "pass_patterns": "Pass Patterns",
    "notable_changes": "Notable Changes",
    "recommendations": "Recommendations",
    "risk_assessment": "Risk Assessment",
}

# html=False escapes any raw HTML in the markdown source — defense in depth
# even though the markdown is produced by our own LLM agent via structured tools.
_md = MarkdownIt("commonmark", {"html": False}).enable("table")
_slack_converter = SlackMarkdownConverter()

# Inline styles for email-safe HTML (many clients strip <style> blocks)
_EMAIL_TABLE_STYLE = 'style="border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 14px;"'
_EMAIL_TH_STYLE = (
    'style="border: 1px solid #ddd; padding: 8px 12px; background-color: #f5f5f5; text-align: left; font-weight: 600;"'
)
_EMAIL_TD_STYLE = 'style="border: 1px solid #ddd; padding: 8px 12px;"'


def _inline_email_styles(html: str) -> str:
    """Add inline styles to HTML elements for email client compatibility."""
    html = html.replace("<table>", f"<table {_EMAIL_TABLE_STYLE}>")
    html = re.sub(r"<th(?=>| )", f"<th {_EMAIL_TH_STYLE}", html)
    html = re.sub(r"<td(?=>| )", f"<td {_EMAIL_TD_STYLE}", html)
    return html


def _make_generation_link(project_id: int, trace_id: str) -> str:
    """Convert a generation/trace ID to a PostHog link."""
    from posthog.utils import absolute_uri

    return absolute_uri(f"/project/{project_id}/llm-analytics/traces/{trace_id}")


def _format_period_for_display(iso_str: str) -> str:
    """Format an ISO-8601 timestamp string for display in emails and Slack messages.

    Parses the ISO string and converts to UTC, returning e.g. "Apr 08, 2026 14:01 UTC".
    Falls back to the raw string if parsing fails, so a bad timestamp never breaks delivery.
    """
    try:
        dt = datetime.fromisoformat(iso_str).astimezone(UTC)
    except (ValueError, TypeError):
        return iso_str
    return dt.strftime("%b %d, %Y %H:%M UTC")


def _linkify_uuids(text: str, project_id: int) -> str:
    """Replace backtick-wrapped UUIDs with clickable links (markdown format)."""

    def replace_with_md_link(match: re.Match) -> str:
        gen_id = match.group(1)
        link = _make_generation_link(project_id, gen_id)
        return f"[{gen_id[:8]}...]({link})"

    return UUID_LINK_PATTERN.sub(replace_with_md_link, text)


def _strip_redundant_leading_heading(content: str, section_title: str) -> str:
    """Strip a leading markdown heading line if it matches the section title.

    The agent sometimes prefixes each section's content with its own heading
    (e.g. `## Executive summary`), which duplicates the heading the renderer
    emits separately. Match on canonical-title prefix so near-matches like
    "Trend analysis (hourly)" are also stripped.
    """
    match = _LEADING_HEADING_RE.match(content)
    if not match:
        return content
    if match.group(1).strip().lower().startswith(section_title.lower()):
        return content[match.end() :].lstrip()
    return content


def _render_section_html(section_name: str, content: str, project_id: int) -> str:
    """Render a report section as HTML with clickable generation ID links."""
    title = SECTION_TITLES.get(section_name, section_name.replace("_", " ").title())
    content = _strip_redundant_leading_heading(content, title)
    # Convert UUIDs to markdown links before rendering so they become <a> tags
    content_with_links = _linkify_uuids(content, project_id)
    html_content = _md.render(content_with_links)
    html_content = _inline_email_styles(html_content)
    return f"<h2>{title}</h2>\n{html_content}\n"


def _render_section_mrkdwn(section_name: str, content: str) -> str:
    """Render a report section as Slack mrkdwn."""
    title = SECTION_TITLES.get(section_name, section_name.replace("_", " ").title())
    content = _strip_redundant_leading_heading(content, title)
    mrkdwn_content = _slack_converter.convert(content)
    return f"*{title}*\n{mrkdwn_content}"


def deliver_email_report(
    report_run,
    targets: list[dict],
    evaluation_name: str,
    evaluation_id: str,
    project_id: int,
    period_start: str,
    period_end: str,
) -> list[str]:
    """Send report via email. Returns list of errors (empty if all succeeded)."""
    from posthog.email import EmailMessage
    from posthog.utils import absolute_uri

    content = EvalReportContent.from_dict(report_run.content)
    errors: list[str] = []

    # Build HTML body from report sections
    body_parts = []
    for section_name in REPORT_SECTIONS:
        section = getattr(content, section_name)
        if section is not None:
            body_parts.append(_render_section_html(section_name, section.content, project_id))

    body_html = "\n".join(body_parts)
    evaluation_url = absolute_uri(f"/project/{project_id}/llm-analytics/evaluations/{evaluation_id}")
    period_start_display = _format_period_for_display(period_start)
    period_end_display = _format_period_for_display(period_end)

    for target in targets:
        if target.get("type") != "email":
            continue

        emails = [e.strip() for e in target.get("value", "").split(",") if e.strip()]
        for email_addr in emails:
            try:
                message = EmailMessage(
                    campaign_key=f"eval_report_{report_run.report_id}_{report_run.id}",
                    subject=f"Evaluation report: {evaluation_name} ({period_start[:10]} - {period_end[:10]})",
                    template_name="evaluation_report",
                    template_context={
                        "evaluation_name": evaluation_name,
                        "period_start": period_start_display,
                        "period_end": period_end_display,
                        "report_body": body_html,
                        "evaluation_url": evaluation_url,
                    },
                    reply_to="hey@posthog.com",
                )
                message.add_recipient(email=email_addr)
                message.send()
            except Exception as e:
                error_msg = f"Failed to send email to {email_addr}: {e}"
                logger.exception(error_msg)
                errors.append(error_msg)

    return errors


def deliver_slack_report(
    report_run,
    targets: list[dict],
    evaluation_name: str,
    team_id: int,
    project_id: int,
    period_start: str,
    period_end: str,
) -> list[str]:
    """Send report via Slack. Returns list of errors (empty if all succeeded)."""
    from posthog.models.integration import Integration, SlackIntegration

    content = EvalReportContent.from_dict(report_run.content)
    errors: list[str] = []

    for target in targets:
        if target.get("type") != "slack":
            continue

        integration_id = target.get("integration_id")
        channel = target.get("channel", "")
        if not integration_id or not channel:
            continue

        try:
            integration = Integration.objects.get(id=integration_id, team_id=team_id, kind="slack")
            client = SlackIntegration(integration).client

            # Post main message
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"Evaluation report: {evaluation_name}",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Period: {_format_period_for_display(period_start)} → {_format_period_for_display(period_end)}",
                        }
                    ],
                },
            ]

            # Add executive summary as first section
            if content.executive_summary:
                summary_mrkdwn = _slack_converter.convert(content.executive_summary.content)
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": summary_mrkdwn[:3000],
                        },
                    }
                )

            result = client.chat_postMessage(
                channel=channel,
                blocks=blocks,
                text=f"Evaluation report: {evaluation_name}",
            )

            # Post remaining sections as thread replies
            thread_ts = result.get("ts")
            if thread_ts:
                # Skip executive summary (already in main message), post rest in thread
                for section_name in REPORT_SECTIONS[1:]:
                    section = getattr(content, section_name)
                    if section is not None:
                        mrkdwn_text = _render_section_mrkdwn(section_name, section.content)
                        client.chat_postMessage(
                            channel=channel,
                            thread_ts=thread_ts,
                            text=mrkdwn_text[:3000],
                        )

        except Exception as e:
            error_msg = f"Failed to send Slack message to {channel}: {e}"
            logger.exception(error_msg)
            errors.append(error_msg)

    return errors


def deliver_report(report_id: str, report_run_id: str) -> None:
    """Deliver a report run via all configured delivery targets.

    Raises RuntimeError when *all* delivery targets fail, so the calling Temporal
    activity surfaces the failure and the retry policy can take effect. Partial
    failures are persisted via delivery_errors but do not raise.
    """
    from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport, EvaluationReportRun

    report = EvaluationReport.objects.select_related("evaluation", "team").get(id=report_id)
    report_run = EvaluationReportRun.objects.get(id=report_run_id)

    evaluation_name = report.evaluation.name
    evaluation_id = str(report.evaluation_id)
    project_id = report.team.id
    team_id = report.team_id
    period_start = report_run.period_start.isoformat()
    period_end = report_run.period_end.isoformat()
    targets = report.delivery_targets or []

    all_errors: list[str] = []

    # Email delivery
    email_targets = [t for t in targets if t.get("type") == "email"]
    if email_targets:
        all_errors.extend(
            deliver_email_report(
                report_run, email_targets, evaluation_name, evaluation_id, project_id, period_start, period_end
            )
        )

    # Slack delivery
    slack_targets = [t for t in targets if t.get("type") == "slack"]
    if slack_targets:
        all_errors.extend(
            deliver_slack_report(
                report_run, slack_targets, evaluation_name, team_id, project_id, period_start, period_end
            )
        )

    # Update delivery status
    if not all_errors:
        report_run.delivery_status = EvaluationReportRun.DeliveryStatus.DELIVERED
    elif len(all_errors) < len(targets):
        report_run.delivery_status = EvaluationReportRun.DeliveryStatus.PARTIAL_FAILURE
    else:
        report_run.delivery_status = EvaluationReportRun.DeliveryStatus.FAILED

    report_run.delivery_errors = all_errors
    report_run.save(update_fields=["delivery_status", "delivery_errors"])

    # Raise on full failure so Temporal retries the activity
    if report_run.delivery_status == EvaluationReportRun.DeliveryStatus.FAILED:
        raise RuntimeError(f"All delivery targets failed for report {report_id}: {all_errors}")
