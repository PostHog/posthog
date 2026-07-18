"""Delivery logic for evaluation reports (email and Slack).

Content shape: `EvalReportContent` has a `title`, 1-6 titled `sections`, a list
of structured `citations`, and a `metrics` block. The renderers below build the
email HTML body and Slack Block Kit payloads from that shape.
"""

import re
from datetime import UTC, datetime
from urllib.parse import quote, urlencode

import structlog
from markdown_it import MarkdownIt
from markdown_to_mrkdwn import SlackMarkdownConverter

from posthog.temporal.ai_observability.eval_reports.report_agent.schema import (
    Citation,
    EvalReportContent,
    EvalReportMetrics,
)

logger = structlog.get_logger(__name__)

# Matches a leading markdown heading line at the very start of a section's content.
# The renderer (email/Slack/UI) already emits its own section title, so if the agent
# also started the section with its own `## Executive summary` heading we strip it
# to avoid duplicated titles. See EvaluationReportViewer.tsx for the parallel fix.
_LEADING_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*(?:\r?\n|$)")

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

_OUTCOME_LABELS = {
    "boolean": (("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")),
    "sentiment": (("positive", "Positive"), ("neutral", "Neutral"), ("negative", "Negative")),
}

type CitationMap = dict[str, tuple[str, str | None]]
_SAFE_CITATION_LABEL_RE = re.compile(r"^[A-Za-z0-9._~-]{1,8}$")


def _inline_email_styles(html: str) -> str:
    """Add inline styles to HTML elements for email client compatibility."""
    html = html.replace("<table>", f"<table {_EMAIL_TABLE_STYLE}>")
    html = re.sub(r"<th(?=>| )", f"<th {_EMAIL_TH_STYLE}", html)
    html = re.sub(r"<td(?=>| )", f"<td {_EMAIL_TD_STYLE}", html)
    return html


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


def _build_citation_map(citations: list[Citation]) -> CitationMap:
    """Map each cited ID to its trace and optional focused generation."""
    citation_map: CitationMap = {}
    for citation in citations:
        if citation.generation_id and citation.trace_id:
            citation_map[citation.generation_id] = (citation.trace_id, citation.generation_id)
        elif citation.trace_id:
            citation_map[citation.trace_id] = (citation.trace_id, None)
    return citation_map


def _make_trace_link(project_id: int, trace_id: str, generation_id: str | None) -> str:
    """Build a trace URL, optionally focused on a cited generation."""
    from posthog.utils import absolute_uri

    # kea-router decodes the pathname once before matching, so preserve an encoded layer for the scene.
    encoded_trace_id = quote(quote(trace_id, safe=""), safe="")
    path = f"/project/{project_id}/ai-observability/traces/{encoded_trace_id}"
    if generation_id:
        path = f"{path}?{urlencode({'event': generation_id})}"
    return absolute_uri(path)


def _citation_link_label(cited_id: str, generation_id: str | None) -> str:
    """Keep arbitrary IDs from breaking the generated Markdown link label."""
    preview = cited_id[:8]
    if _SAFE_CITATION_LABEL_RE.fullmatch(preview):
        return f"{preview}..."
    return "generation" if generation_id else "trace"


def _linkify_citations(text: str, project_id: int, citation_map: CitationMap) -> str:
    """Replace cited generation or trace IDs with clickable markdown links.

    Uses the structured citation map (from add_citation calls) rather than
    scanning for UUID patterns. Only IDs the agent explicitly cited get linked.
    Handles common LLM formatting wrappers (backticks, angle brackets).

    Two-phase approach avoids double-replacement: first swap every occurrence
    of each cited ID to a unique placeholder, then replace placeholders with the
    actual markdown links. This prevents cited IDs inside URLs from being matched.
    """
    if not citation_map:
        return text

    # Phase 1: replace all occurrences of each cited ID with a placeholder.
    placeholders: dict[str, str] = {}
    for i, cited_id in enumerate(citation_map):
        placeholder = f"\x00CITE{i}\x00"
        placeholders[placeholder] = cited_id
        _, generation_id = citation_map[cited_id]

        for wrapper in [f"`` `{cited_id}` ``", f"`{cited_id}`", f"<{cited_id}>"]:
            text = text.replace(wrapper, placeholder)
        if generation_id:
            text = text.replace(cited_id, placeholder)

    # Phase 2: replace placeholders with markdown links.
    for placeholder, cited_id in placeholders.items():
        trace_id, generation_id = citation_map[cited_id]
        link = _make_trace_link(project_id, trace_id, generation_id)
        label = _citation_link_label(cited_id, generation_id)
        text = text.replace(placeholder, f"[{label}]({link})")

    return text


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


def _format_pass_rate(rate: float | None) -> str:
    if rate is None:
        return "—"
    return f"{rate:.2f}%"


def _format_outcome_value(metrics: EvalReportMetrics, outcome: str) -> str:
    count = metrics.result_counts[outcome]
    if metrics.output_type == "boolean":
        return str(count)

    rate = metrics.result_rates.get(outcome)
    value = str(count) if rate is None else f"{count} ({_format_pass_rate(rate)})"

    previous_rate = (metrics.previous_result_rates or {}).get(outcome)
    if rate is None or previous_rate is None:
        return value

    diff = rate - previous_rate
    arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "•")
    return f"{value} {arrow} {abs(diff):.2f}pp"


def _format_boolean_pass_rate_value(metrics: EvalReportMetrics) -> str:
    value = _format_pass_rate(metrics.pass_rate)
    if metrics.previous_pass_rate is None:
        return value

    diff = metrics.pass_rate - metrics.previous_pass_rate
    arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "•")
    return f"{value} ({arrow} {abs(diff):.2f}pp vs previous)"


_METRICS_UNAVAILABLE_NOTICE = (
    "Metrics could not be computed for this period because the analytics store was "
    "temporarily unavailable. This does not mean no evaluations ran."
)


def _render_metrics_block_html(metrics: EvalReportMetrics) -> str:
    """Render trusted outcome counts and rates as an HTML table.

    Lives at the top of the email body so the reader sees the trusted numbers
    before reading the agent's analysis.
    """
    period = f"{_format_period_for_display(metrics.period_start)} → {_format_period_for_display(metrics.period_end)}"
    if not metrics.metrics_available:
        # Never render a failed query as a real "0 runs" table.
        notice = _inline_email_styles(f"<p><strong>{_METRICS_UNAVAILABLE_NOTICE}</strong></p>")
        return f'<p class="muted"><strong>Period</strong>: {period}</p>\n{notice}\n'
    outcome_labels = _OUTCOME_LABELS[metrics.output_type]
    headers = "".join(f"<th>{label}</th>" for _, label in outcome_labels)
    values = "".join(f"<td>{_format_outcome_value(metrics, outcome)}</td>" for outcome, _ in outcome_labels)
    if metrics.output_type == "boolean":
        headers += "<th>Pass rate</th>"
        values += f"<td><strong>{_format_boolean_pass_rate_value(metrics)}</strong></td>"
    table = f"<table><tr><th>Total runs</th>{headers}</tr><tr><td>{metrics.total_runs}</td>{values}</tr></table>"
    table = _inline_email_styles(table)
    return f'<p class="muted"><strong>Period</strong>: {period}</p>\n{table}\n'


def _render_metrics_slack_blocks(metrics: EvalReportMetrics) -> list[dict]:
    """Render the metrics block as a compact, output-type-neutral Slack dashboard."""
    if not metrics.metrics_available:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": _METRICS_UNAVAILABLE_NOTICE}}]
    outcome_lines = [
        f"{label}: {_format_outcome_value(metrics, outcome)}" for outcome, label in _OUTCOME_LABELS[metrics.output_type]
    ]
    if metrics.output_type == "boolean":
        outcome_lines.append(f"Pass rate: {_format_boolean_pass_rate_value(metrics)}")
    code_block = "\n".join([f"Total runs: {metrics.total_runs}", *outcome_lines])

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```{code_block}```"},
        },
    ]
    return blocks


def _render_section_html(title: str, content: str, project_id: int, citation_map: CitationMap) -> str:
    """Render a titled markdown section as HTML with clickable trace links."""
    content = _strip_redundant_leading_heading(content, title)
    content_with_links = _linkify_citations(content, project_id, citation_map)
    html_content = _md.render(content_with_links)
    html_content = _inline_email_styles(html_content)
    return f"<h2>{title}</h2>\n{html_content}\n"


def _render_section_mrkdwn(title: str, content: str, project_id: int, citation_map: CitationMap) -> str:
    """Render a titled markdown section as Slack mrkdwn with clickable trace links."""
    content = _strip_redundant_leading_heading(content, title)
    content = _linkify_citations(content, project_id, citation_map)
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
    citation_map = _build_citation_map(content.citations)
    errors: list[str] = []

    # Metrics block first, then each section
    body_parts = [_render_metrics_block_html(content.metrics)]
    for section in content.sections:
        body_parts.append(_render_section_html(section.title, section.content, project_id, citation_map))
    body_html = "\n".join(body_parts)

    evaluation_url = absolute_uri(f"/project/{project_id}/ai-evals/evaluations/{evaluation_id}")
    period_start_display = _format_period_for_display(period_start)
    period_end_display = _format_period_for_display(period_end)
    subject_title = content.title or "Evaluation report"
    subject = f"{evaluation_name}: {subject_title}"

    for target in targets:
        if target.get("type") != "email":
            continue

        emails = [e.strip() for e in target.get("value", "").split(",") if e.strip()]
        for email_addr in emails:
            try:
                message = EmailMessage(
                    campaign_key=f"eval_report_{report_run.report_id}_{report_run.id}",
                    subject=subject,
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
    """Send report via Slack. Returns list of errors (empty if all succeeded).

    Main message = agent title (Block Kit header) + metrics context + first section.
    Thread replies = sections[1:]. If there's only one section, no thread replies.
    """
    from posthog.models.integration import Integration, SlackIntegration

    content = EvalReportContent.from_dict(report_run.content)
    citation_map = _build_citation_map(content.citations)
    errors: list[str] = []

    header_text = f"{evaluation_name}: {content.title}" if content.title else f"Evaluation report: {evaluation_name}"
    # Slack header blocks are limited to 150 chars, enforce that here.
    if len(header_text) > 150:
        header_text = header_text[:147] + "..."

    period_line = (
        f"*{evaluation_name}*  ·  {_format_period_for_display(period_start)} → {_format_period_for_display(period_end)}"
    )

    for target in targets:
        if target.get("type") != "slack":
            continue

        integration_id = target.get("integration_id")
        channel = target.get("channel", "")
        if not integration_id or not channel:
            continue

        # The Slack channel picker stores the target as "<channel_id>|#<channel_name>"
        # (e.g. "C0B5CHB0JQH|#tech-devops-cron"). chat.postMessage only accepts the channel
        # ID, so strip the "|#name" suffix before sending. Mirrors the subscriptions path in
        # ee/tasks/subscriptions/slack_subscriptions.py, which splits the same composite value.
        channel_id = channel.split("|")[0]
        if not channel_id:
            error_msg = f"Failed to send Slack message to {channel}: no channel ID in target value"
            logger.warning(error_msg)
            errors.append(error_msg)
            continue

        try:
            integration = Integration.objects.get(id=integration_id, team_id=team_id, kind="slack")
            client = SlackIntegration(integration).client

            # Main message: header + context + metrics grid + first section (if any)
            blocks: list[dict] = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": header_text},
                },
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": period_line}],
                },
                *_render_metrics_slack_blocks(content.metrics),
                {"type": "divider"},
            ]

            if content.sections:
                first_section_mrkdwn = _render_section_mrkdwn(
                    content.sections[0].title, content.sections[0].content, project_id, citation_map
                )
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": first_section_mrkdwn[:3000]},
                    }
                )

            result = client.chat_postMessage(
                channel=channel_id,
                blocks=blocks,
                text=header_text,
            )

            # Thread replies: remaining sections, one per reply
            thread_ts = result.get("ts")
            if thread_ts and len(content.sections) > 1:
                for section in content.sections[1:]:
                    mrkdwn_text = _render_section_mrkdwn(section.title, section.content, project_id, citation_map)
                    client.chat_postMessage(
                        channel=channel_id,
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

    Raises RuntimeError after persisting FAILED status if ALL delivery targets
    fail, so the Temporal activity surfaces the failure and the retry policy
    kicks in. Partial failures return normally (with delivery_status=partial_failure).
    """
    from products.ai_observability.backend.models.evaluation_reports import EvaluationReport, EvaluationReportRun

    report_run = EvaluationReportRun.objects.get(id=report_run_id)
    report = EvaluationReport.objects.select_related("evaluation", "team").get(id=report_id)

    evaluation_name = report.evaluation.name
    evaluation_id = str(report.evaluation.id)
    project_id = report.team.id
    team_id = report.team_id
    period_start = report_run.period_start.isoformat()
    period_end = report_run.period_end.isoformat()
    targets = report.delivery_targets or []

    all_errors: list[str] = []

    email_targets = [t for t in targets if t.get("type") == "email"]
    email_errors: list[str] = []
    if email_targets:
        email_errors = deliver_email_report(
            report_run, email_targets, evaluation_name, evaluation_id, project_id, period_start, period_end
        )
        all_errors.extend(email_errors)

    slack_targets = [t for t in targets if t.get("type") == "slack"]
    slack_errors: list[str] = []
    if slack_targets:
        slack_errors = deliver_slack_report(
            report_run, slack_targets, evaluation_name, team_id, project_id, period_start, period_end
        )
        all_errors.extend(slack_errors)

    had_any_target = bool(email_targets or slack_targets)
    # Each email target may contain multiple comma-separated addresses, and deliver_email_report
    # appends one error per address that fails — so count attempts per address, not per target.
    email_attempts = sum(
        len([addr.strip() for addr in t.get("value", "").split(",") if addr.strip()]) for t in email_targets
    )
    slack_attempts = len(slack_targets)
    total_attempts = email_attempts + slack_attempts
    all_failed = had_any_target and total_attempts > 0 and len(all_errors) >= total_attempts

    from posthog.temporal.ai_observability.eval_reports.metrics import increment_delivery

    for _ in range(email_attempts - len(email_errors)):
        increment_delivery("email", "delivered")
    for _ in range(len(email_errors)):
        increment_delivery("email", "failed")
    for _ in range(slack_attempts - len(slack_errors)):
        increment_delivery("slack", "delivered")
    for _ in range(len(slack_errors)):
        increment_delivery("slack", "failed")

    if not had_any_target:
        # Report generated successfully, but no delivery target is configured, so there is nothing to send.
        report_run.delivery_status = EvaluationReportRun.DeliveryStatus.GENERATED
    elif all_failed:
        report_run.delivery_status = EvaluationReportRun.DeliveryStatus.FAILED
    elif all_errors:
        report_run.delivery_status = EvaluationReportRun.DeliveryStatus.PARTIAL_FAILURE
    else:
        report_run.delivery_status = EvaluationReportRun.DeliveryStatus.DELIVERED

    report_run.delivery_errors = all_errors
    report_run.save(update_fields=["delivery_status", "delivery_errors"])

    logger.info(
        "llma_eval_reports_delivery_completed",
        report_id=report_id,
        report_run_id=report_run_id,
        delivery_status=report_run.delivery_status,
        email_targets=len(email_targets),
        slack_targets=len(slack_targets),
        error_count=len(all_errors),
    )

    if all_failed:
        # Raise so the Temporal activity fails and retries fire per DELIVER_RETRY_POLICY.
        raise RuntimeError(f"All delivery targets failed for report run {report_run_id}: {'; '.join(all_errors)}")
