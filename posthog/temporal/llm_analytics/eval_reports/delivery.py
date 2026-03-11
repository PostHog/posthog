"""Delivery logic for evaluation reports (email and Slack)."""

import re

import structlog

from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import REPORT_SECTIONS, EvalReportContent

logger = structlog.get_logger(__name__)

UUID_LINK_PATTERN = re.compile(r"`([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})`")

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


def _make_generation_link(project_id: int, trace_id: str) -> str:
    """Convert a generation/trace ID to a PostHog link."""
    from posthog.utils import absolute_uri

    return absolute_uri(f"/project/{project_id}/llm-analytics/traces/{trace_id}")


def _render_section_html(section_name: str, content: str, project_id: int) -> str:
    """Render a report section as HTML with clickable generation ID links."""
    title = SECTION_TITLES.get(section_name, section_name.replace("_", " ").title())

    def replace_id_with_link(match):
        gen_id = match.group(1)
        link = _make_generation_link(project_id, gen_id)
        return f'<a href="{link}" style="font-family: monospace; font-size: 0.85em;">{gen_id[:8]}...</a>'

    html_content = UUID_LINK_PATTERN.sub(replace_id_with_link, content)
    # Basic markdown → HTML: bold, line breaks, bullet points
    html_content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_content)
    html_content = html_content.replace("\n- ", "\n<li>")
    html_content = html_content.replace("\n", "<br>\n")

    return f"<h2>{title}</h2>\n<div>{html_content}</div>\n"


def deliver_email_report(
    report_run,
    targets: list[dict],
    evaluation_name: str,
    project_id: int,
    period_start: str,
    period_end: str,
) -> list[str]:
    """Send report via email. Returns list of errors (empty if all succeeded)."""
    from posthog.email import EmailMessage

    content = EvalReportContent.from_dict(report_run.content)
    errors: list[str] = []

    # Build HTML body from report sections
    body_parts = []
    for section_name in REPORT_SECTIONS:
        section = getattr(content, section_name)
        if section is not None:
            body_parts.append(_render_section_html(section_name, section.content, project_id))

    body_html = "\n".join(body_parts)

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
                        "period_start": period_start,
                        "period_end": period_end,
                        "report_body": body_html,
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
    from posthog.models.integration import Integration

    content = EvalReportContent.from_dict(report_run.content)
    errors: list[str] = []

    # Build plain text summary for Slack
    summary_parts = []
    for section_name in REPORT_SECTIONS:
        section = getattr(content, section_name)
        if section is not None:
            title = SECTION_TITLES.get(section_name, section_name)
            summary_parts.append(f"*{title}*\n{section.content}")

    for target in targets:
        if target.get("type") != "slack":
            continue

        integration_id = target.get("integration_id")
        channel = target.get("channel", "")
        if not integration_id or not channel:
            continue

        try:
            integration = Integration.objects.get(id=integration_id, team_id=team_id, kind="slack")
            client = integration.slack_client()

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
                            "text": f"Period: {period_start[:10]} to {period_end[:10]}",
                        }
                    ],
                },
            ]

            # Add executive summary as first section
            if content.executive_summary:
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": content.executive_summary.content[:3000],
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
            if thread_ts and len(summary_parts) > 1:
                # Skip executive summary (already in main message), post rest in thread
                for section_name in REPORT_SECTIONS[1:]:
                    section = getattr(content, section_name)
                    if section is not None:
                        title = SECTION_TITLES.get(section_name, section_name)
                        client.chat_postMessage(
                            channel=channel,
                            thread_ts=thread_ts,
                            text=f"*{title}*\n{section.content[:3000]}",
                        )

        except Exception as e:
            error_msg = f"Failed to send Slack message to {channel}: {e}"
            logger.exception(error_msg)
            errors.append(error_msg)

    return errors


def deliver_report(report_id: str, report_run_id: str) -> None:
    """Deliver a report run via all configured delivery targets."""
    from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport, EvaluationReportRun

    report = EvaluationReport.objects.select_related("evaluation", "team").get(id=report_id)
    report_run = EvaluationReportRun.objects.get(id=report_run_id)

    evaluation_name = report.evaluation.name
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
            deliver_email_report(report_run, email_targets, evaluation_name, project_id, period_start, period_end)
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
