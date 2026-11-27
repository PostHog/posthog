"""Delivery logic for evaluation reports (email and Slack).

Content shape: `EvalReportContent` has a `title`, 1-6 titled `sections`, a list
of structured `citations`, and a `metrics` block. The renderers below build the
email HTML body and Slack Block Kit payloads from that shape.
"""

import re
import html
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote, urlencode

import structlog
from markdown_it import MarkdownIt
from markdown_it.token import Token
from markdown_to_mrkdwn import SlackMarkdownConverter
from slack_sdk.errors import SlackApiError

from posthog.dataclasses import frozen
from posthog.helpers.email_utils import defang_urls
from posthog.models.team import Team
from posthog.slack.formatting import channel_id_from_target, escape_slack_mrkdwn
from posthog.temporal.ai_observability.eval_reports.auto_disable import disable_undeliverable_report
from posthog.temporal.ai_observability.eval_reports.report_agent.schema import (
    METRICS_UNAVAILABLE_MESSAGE,
    Citation,
    EvalReportContent,
    EvalReportMetrics,
    citation_wrappers,
)

logger = structlog.get_logger(__name__)

# Matches a leading markdown heading line at the very start of a section's content.
# The renderer (email/Slack/UI) already emits its own section title, so if the agent
# also started the section with its own `## Executive summary` heading we strip it
# to avoid duplicated titles. See EvaluationReportViewer.tsx for the parallel fix.
_LEADING_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*(?:\r?\n|$)")


# The agent writes the markdown, but it reads customer trace content, so a prompt injection can steer
# what it writes. Both renderers make only the citation links clickable: in email, html=False escapes raw
# HTML, images are off, links render only when they point at a cited trace, and URL-shaped text is defanged.
class _CitationLinksMarkdownIt(MarkdownIt):
    def __init__(self, citation_urls: set[str]):
        super().__init__("commonmark", {"html": False})
        self.enable("table").disable("image")
        self._citation_urls = {self.normalizeLink(url) for url in citation_urls}
        # Mail clients auto-link URL- and domain-shaped text, so every text and code node is defanged too.
        self.add_render_rule("text", lambda _renderer, tokens, idx, _options, _env: _defang(tokens[idx]))
        self.add_render_rule(
            "code_inline", lambda _renderer, tokens, idx, _options, _env: f"<code>{_defang(tokens[idx])}</code>"
        )
        for block in ("code_block", "fence"):
            self.add_render_rule(
                block,
                lambda _renderer, tokens, idx, _options, _env: f"<pre><code>{_defang(tokens[idx])}</code></pre>\n",
            )

    def validateLink(self, url: str) -> bool:
        return url in self._citation_urls


def _defang(token: Token) -> str:
    return defang_urls(html.escape(token.content))


_INVITE_UTM_TAGS = "utm_source=posthog&utm_campaign=eval_report&utm_medium=slack"

_EMAIL_NO_ADDRESSES_ERROR = (
    "Failed to send email: The email destination has no addresses. Add an address or remove the email destination."
)

_SLACK_RECONNECT_HINT = "The Slack connection no longer works. Reconnect Slack in your project settings."
# Slack errors that no retry can fix, each with the step the user must take.
_SLACK_CONFIG_ERROR_HINTS = {
    "not_in_channel": "The PostHog app is not in this channel. Invite it with /invite @PostHog.",
    "is_archived": "This channel is archived. Pick a different channel for this report.",
    # Slack also returns channel_not_found for a private channel that the app is not a member of.
    "channel_not_found": (
        "Slack can't find this channel. If the channel is private, invite the PostHog app with /invite @PostHog. "
        "Otherwise, pick a different channel for this report."
    ),
    **dict.fromkeys(
        ("account_inactive", "invalid_auth", "token_revoked", "missing_scope", "not_allowed_token_type"),
        _SLACK_RECONNECT_HINT,
    ),
}

# Inline styles for email-safe HTML (many clients strip <style> blocks)
_EMAIL_TABLE_STYLE = 'style="border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 14px;"'
_EMAIL_TH_STYLE = (
    'style="border: 1px solid #ddd; padding: 8px 12px; background-color: #f5f5f5; text-align: left; font-weight: 600;"'
)
_EMAIL_TD_STYLE = 'style="border: 1px solid #ddd; padding: 8px 12px;"'

_OUTCOME_LABELS = {
    "boolean": (("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")),
    "numeric": (("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")),
    "categorical": (("pass", "Pass"), ("fail", "Fail"), ("na", "N/A")),
    "sentiment": (("positive", "Positive"), ("neutral", "Neutral"), ("negative", "Negative")),
}

type CitationMap = dict[str, CitationLink]
_SAFE_CITATION_LABEL_RE = re.compile(r"^[A-Za-z0-9._~-]{1,8}$")


@dataclass(frozen=True, kw_only=True)
class CitationLink:
    """Where a cited ID should take the reader, and what to call it if the ID doesn't render."""

    trace_id: str
    generation_id: str | None
    session_id: str | None


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
    """Map each cited ID to the unit the reader should land on."""
    citation_map: CitationMap = {}
    for citation in citations:
        if citation.session_id:
            citation_map[citation.session_id] = CitationLink(
                trace_id=citation.trace_id, generation_id=None, session_id=citation.session_id
            )
        elif citation.generation_id and citation.trace_id:
            citation_map[citation.generation_id] = CitationLink(
                trace_id=citation.trace_id, generation_id=citation.generation_id, session_id=None
            )
        elif citation.trace_id:
            citation_map[citation.trace_id] = CitationLink(
                trace_id=citation.trace_id, generation_id=None, session_id=None
            )
    return citation_map


def _make_citation_link(project_id: int, link: CitationLink) -> str:
    """Build the URL for a cited unit: its session, or its trace optionally focused on a generation."""
    from posthog.utils import absolute_uri

    # One encoded layer each, matching what the app's own URL builders emit: the session scene
    # reads the ID straight off the decoded pathname, while the trace scene decodes once more.
    if link.session_id:
        return absolute_uri(f"/project/{project_id}/ai-observability/sessions/{quote(link.session_id, safe='')}")

    encoded_trace_id = quote(quote(link.trace_id, safe=""), safe="")
    path = f"/project/{project_id}/ai-observability/traces/{encoded_trace_id}"
    if link.generation_id:
        path = f"{path}?{urlencode({'event': link.generation_id})}"
    return absolute_uri(path)


def _citation_link_label(cited_id: str, link: CitationLink) -> str:
    """Keep arbitrary IDs from breaking the generated Markdown link label."""
    preview = cited_id[:8]
    if _SAFE_CITATION_LABEL_RE.fullmatch(preview):
        return f"{preview}..."
    if link.session_id:
        return "session"
    return "generation" if link.generation_id else "trace"


def _citation_placeholders(text: str, citation_map: CitationMap) -> tuple[str, dict[str, str]]:
    """Swap every cited generation or trace ID for a unique placeholder, mapped back to its ID.

    Uses the structured citation map (from add_citation calls) rather than
    scanning for UUID patterns. Only IDs the agent explicitly cited get linked.
    Handles common LLM formatting wrappers (backticks, angle brackets).

    Swapping every ID before any link is written keeps cited IDs inside the
    generated URLs from being matched again.
    """
    placeholders: dict[str, str] = {}
    for i, cited_id in enumerate(citation_map):
        placeholder = f"\x00CITE{i}\x00"
        placeholders[placeholder] = cited_id

        for wrapper in citation_wrappers(cited_id):
            text = text.replace(wrapper, placeholder)
        if citation_map[cited_id].generation_id:
            text = text.replace(cited_id, placeholder)
    return text, placeholders


def _linkify_citations(text: str, project_id: int, citation_map: CitationMap) -> str:
    """Replace cited generation or trace IDs with clickable markdown links."""
    return _write_markdown_citation_links(*_citation_placeholders(text, citation_map), project_id, citation_map)


def _write_markdown_citation_links(
    text: str, placeholders: dict[str, str], project_id: int, citation_map: CitationMap
) -> str:
    for placeholder, cited_id in placeholders.items():
        link = citation_map[cited_id]
        text = text.replace(
            placeholder, f"[{_citation_link_label(cited_id, link)}]({_make_citation_link(project_id, link)})"
        )
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
    if metrics.output_type in ("boolean", "numeric", "categorical"):
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
    if metrics.pass_rate is None or metrics.previous_pass_rate is None:
        return value

    diff = metrics.pass_rate - metrics.previous_pass_rate
    arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "•")
    return f"{value} ({arrow} {abs(diff):.2f}pp vs previous)"


def _render_metrics_block_html(
    metrics: EvalReportMetrics | None,
    *,
    period_start: str = "",
    period_end: str = "",
) -> str:
    """Render trusted outcome counts and rates as an HTML table.

    Lives at the top of the email body so the reader sees the trusted numbers
    before reading the agent's analysis.
    """
    if metrics is None:
        period = f"{_format_period_for_display(period_start)} → {_format_period_for_display(period_end)}"
        notice = _inline_email_styles(f"<p><strong>{METRICS_UNAVAILABLE_MESSAGE}</strong></p>")
        return f'<p class="muted"><strong>Period</strong>: {period}</p>\n{notice}\n'
    period = f"{_format_period_for_display(metrics.period_start)} → {_format_period_for_display(metrics.period_end)}"
    outcome_labels = _OUTCOME_LABELS[metrics.output_type]
    headers = "".join(f"<th>{label}</th>" for _, label in outcome_labels)
    values = "".join(f"<td>{_format_outcome_value(metrics, outcome)}</td>" for outcome, _ in outcome_labels)
    if metrics.output_type in ("boolean", "numeric", "categorical"):
        headers += "<th>Pass rate</th>"
        values += f"<td><strong>{_format_boolean_pass_rate_value(metrics)}</strong></td>"
    table = f"<table><tr><th>Total runs</th>{headers}</tr><tr><td>{metrics.total_runs}</td>{values}</tr></table>"
    table = _inline_email_styles(table)
    return f'<p class="muted"><strong>Period</strong>: {period}</p>\n{table}\n'


def _render_metrics_slack_blocks(metrics: EvalReportMetrics | None) -> list[dict]:
    """Render the metrics block as a compact, output-type-neutral Slack dashboard."""
    if metrics is None:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": METRICS_UNAVAILABLE_MESSAGE}}]
    outcome_lines = [
        f"{label}: {_format_outcome_value(metrics, outcome)}" for outcome, label in _OUTCOME_LABELS[metrics.output_type]
    ]
    if metrics.output_type in ("boolean", "numeric", "categorical"):
        outcome_lines.append(f"Pass rate: {_format_boolean_pass_rate_value(metrics)}")
    code_block = "\n".join([f"Total runs: {metrics.total_runs}", *outcome_lines])

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```{code_block}```"},
        },
    ]
    return blocks


# The agent writes sections without a length cap, and Slack conversion is super-linear on adversarial markdown, so
# longer text is cut before it runs.
_MAX_SECTION_CHARS = 20_000


def _prepare_section(title: str, content: str, citation_map: CitationMap) -> tuple[str, dict[str, str]]:
    """Cited IDs become placeholders before anything parses the text, so no later step can split or escape them."""
    content = _strip_redundant_leading_heading(content[:_MAX_SECTION_CHARS], title)
    return _citation_placeholders(content, citation_map)


def _render_section_html(title: str, content: str, project_id: int, citation_map: CitationMap) -> str:
    """Render a titled markdown section as HTML with clickable trace links."""
    content = _write_markdown_citation_links(*_prepare_section(title, content, citation_map), project_id, citation_map)
    md = _CitationLinksMarkdownIt({_make_citation_link(project_id, link) for link in citation_map.values()})
    html_content = _inline_email_styles(md.render(content))
    return f"<h2>{defang_urls(html.escape(title))}</h2>\n{html_content}\n"


def _render_section_mrkdwn(title: str, content: str, project_id: int, citation_map: CitationMap) -> str:
    """Render a titled markdown section as Slack mrkdwn with clickable trace links."""
    content, placeholders = _prepare_section(title, content, citation_map)
    content = content.replace("&", "&amp;")
    # Whatever syntax the agent used, a live `<!channel>` or `<url|label>` needs a `<`, so every `<` left
    # after conversion is escaped and only citation links are written back.
    # Slack auto-links domain-shaped text too, so it is defanged.
    # A fresh converter per section, since it keeps code-block state and a section can end inside a fence.
    mrkdwn_content = defang_urls(SlackMarkdownConverter().convert(content)).replace("<", "&lt;")
    for placeholder, cited_id in placeholders.items():
        link = citation_map[cited_id]
        mrkdwn_content = mrkdwn_content.replace(
            placeholder, f"<{_make_citation_link(project_id, link)}|{_citation_link_label(cited_id, link)}>"
        )
    return f"*{escape_slack_mrkdwn(defang_urls(title[:_MAX_SECTION_CHARS]))}*\n{mrkdwn_content}"


def _report_url(project_id: int, evaluation_id: str, report_run_id: str) -> str:
    from posthog.utils import absolute_uri

    # report_run is the evaluation page's URL param that opens this report in its drawer.
    return absolute_uri(f"/project/{project_id}/ai-evals/evaluations/{evaluation_id}?report_run={report_run_id}")


def _email_addresses(target: dict) -> list[str]:
    value = target.get("value")
    if not isinstance(value, str):
        return []
    return [address.strip() for address in value.split(",") if address.strip()]


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

    content = EvalReportContent.from_dict(report_run.content)
    citation_map = _build_citation_map(content.citations)
    errors: list[str] = []

    # Metrics block first, then each section
    body_parts = [_render_metrics_block_html(content.metrics, period_start=period_start, period_end=period_end)]
    for section in content.sections:
        body_parts.append(_render_section_html(section.title, section.content, project_id, citation_map))
    body_html = "\n".join(body_parts)

    evaluation_url = _report_url(project_id, evaluation_id, str(report_run.id))
    period_start_display = _format_period_for_display(period_start)
    period_end_display = _format_period_for_display(period_end)
    subject_title = content.title or "Evaluation report"
    subject = f"{evaluation_name}: {subject_title}"

    for target in targets:
        if target.get("type") != "email":
            continue

        for email_addr in _email_addresses(target):
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


@frozen
class SlackDeliveryFailure:
    message: str
    retryable: bool


def _slack_channel_label(target_channel: str) -> str:
    return target_channel.partition("|")[2] or target_channel


def _slack_config_failure(target_channel: str, hint: str) -> SlackDeliveryFailure:
    error_msg = f"Failed to send Slack message to {_slack_channel_label(target_channel)}: {hint}"
    logger.warning(error_msg)
    return SlackDeliveryFailure(message=error_msg, retryable=False)


def _slack_delivery_failure(target_channel: str, error: Exception) -> SlackDeliveryFailure:
    if isinstance(error, SlackApiError) and (hint := _SLACK_CONFIG_ERROR_HINTS.get(error.response.get("error"))):
        return _slack_config_failure(target_channel, hint)
    error_msg = f"Failed to send Slack message to {_slack_channel_label(target_channel)}: {error}"
    logger.exception(error_msg)
    return SlackDeliveryFailure(message=error_msg, retryable=True)


def deliver_slack_report(
    report_run,
    targets: list[dict],
    evaluation_name: str,
    evaluation_id: str,
    team_id: int,
    project_id: int,
    period_start: str,
    period_end: str,
) -> list[SlackDeliveryFailure]:
    """Send report via Slack. Returns one failure per failed target (empty if all succeeded).

    Main message = agent title (Block Kit header) + metrics context + first section.
    Thread replies = sections[1:]. If there's only one section, no thread replies.
    """
    from posthog.integrations import IntegrationManager, IntegrationNotFound
    from posthog.models.integration import SlackIntegration

    from products.slack_app.backend.facade.api import slack_followup_invite

    content = EvalReportContent.from_dict(report_run.content)
    citation_map = _build_citation_map(content.citations)
    failures: list[SlackDeliveryFailure] = []

    # Slack auto-links URLs even in the plain-text header, so the evaluation name and title are defanged.
    name = defang_urls(evaluation_name)
    header_text = f"{name}: {defang_urls(content.title)}" if content.title else f"Evaluation report: {name}"
    # Slack header blocks are limited to 150 chars, enforce that here.
    if len(header_text) > 150:
        header_text = header_text[:147] + "..."

    report_url = _report_url(project_id, evaluation_id, str(report_run.id))
    period_line = (
        f"*{escape_slack_mrkdwn(name)}*  ·  {_format_period_for_display(period_start)} → {_format_period_for_display(period_end)}"
        f"  ·  <{report_url}|Open in PostHog>"
    )

    team = Team.objects.select_related("organization").get(id=team_id)
    # Read rather than assumed: nothing on this path enforces consent before generation.
    ai_enabled = bool(team.organization.is_ai_data_processing_approved)

    for target in targets:
        if target.get("type") != "slack":
            continue

        integration_id = target.get("integration_id")
        channel = target.get("channel", "")
        if not integration_id or not channel:
            continue

        channel_id = channel_id_from_target(channel)
        if not channel_id:
            error_msg = f"Failed to send Slack message to {channel}: no channel ID in target value"
            logger.warning(error_msg)
            failures.append(SlackDeliveryFailure(message=error_msg, retryable=False))
            continue

        try:
            integration = IntegrationManager.slack.oauth.get(team_id, integration_id)
            client = SlackIntegration(integration, source="eval_reports").client

            # Main message: header + context + metrics grid + first section (if any)
            blocks: list[dict] = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": header_text},
                },
                {
                    "type": "context",
                    # Verbatim, so an evaluation name such as `@here` is not parsed into a broadcast mention.
                    "elements": [{"type": "mrkdwn", "text": period_line, "verbatim": True}],
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
                        "text": {"type": "mrkdwn", "text": first_section_mrkdwn[:3000], "verbatim": True},
                    }
                )

            if invite := slack_followup_invite(integration, utm_tags=_INVITE_UTM_TAGS, ai_enabled=ai_enabled):
                blocks.append(invite)

            result = client.chat_postMessage(
                channel=channel_id,
                blocks=blocks,
                text=escape_slack_mrkdwn(header_text),
                parse="none",
                unfurl_links=False,
                unfurl_media=False,
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
                        parse="none",
                        unfurl_links=False,
                        unfurl_media=False,
                    )

        except IntegrationNotFound:
            # delivery_targets is a JSON field, so a deleted Slack integration leaves its id behind.
            failures.append(_slack_config_failure(channel, _SLACK_RECONNECT_HINT))
        except Exception as e:
            failures.append(_slack_delivery_failure(channel, e))

    return failures


def _report_destinations(targets: list[dict]) -> list[dict[str, str]]:
    destinations: list[dict[str, str]] = []
    for target in targets:
        if target.get("type") == "email":
            destinations.extend({"type": "email", "name": address} for address in _email_addresses(target))
        elif target.get("type") == "slack" and target.get("channel"):
            destinations.append({"type": "slack", "name": _slack_channel_label(target["channel"])})
    return destinations


def deliver_report(report_id: str, report_run_id: str) -> None:
    """Deliver a report run via all configured delivery targets.

    Raises RuntimeError after persisting FAILED status if ALL delivery targets
    fail, so the Temporal activity surfaces the failure and the retry policy
    kicks in. Partial failures return normally (with delivery_status=partial_failure).
    If every failure is a configuration error, a retry cannot fix it, so the
    report is disabled and its creator notified instead.
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
    email_config_errors = [_EMAIL_NO_ADDRESSES_ERROR for t in email_targets if not _email_addresses(t)]
    all_errors.extend(email_config_errors)
    email_errors: list[str] = []
    if email_targets:
        email_errors = deliver_email_report(
            report_run, email_targets, evaluation_name, evaluation_id, project_id, period_start, period_end
        )
        all_errors.extend(email_errors)

    slack_targets = [t for t in targets if t.get("type") == "slack"]
    slack_failures: list[SlackDeliveryFailure] = []
    if slack_targets:
        slack_failures = deliver_slack_report(
            report_run, slack_targets, evaluation_name, evaluation_id, team_id, project_id, period_start, period_end
        )
        all_errors.extend(failure.message for failure in slack_failures)

    had_any_target = bool(email_targets or slack_targets)
    # Each email target may contain multiple comma-separated addresses, and deliver_email_report
    # appends one error per address that fails — so count attempts per address, not per target.
    email_attempts = sum(len(_email_addresses(t)) for t in email_targets)
    slack_attempts = len(slack_targets)
    total_attempts = email_attempts + len(email_config_errors) + slack_attempts
    all_failed = had_any_target and total_attempts > 0 and len(all_errors) >= total_attempts

    from posthog.temporal.ai_observability.eval_reports.metrics import increment_delivery

    for _ in range(email_attempts - len(email_errors)):
        increment_delivery("email", "delivered")
    for _ in range(len(email_errors) + len(email_config_errors)):
        increment_delivery("email", "failed")
    for _ in range(slack_attempts - len(slack_failures)):
        increment_delivery("slack", "delivered")
    for _ in range(len(slack_failures)):
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
    report_run.delivery_destinations = _report_destinations(targets)
    report_run.save(update_fields=["delivery_status", "delivery_errors", "delivery_destinations"])

    logger.info(
        "llma_eval_reports_delivery_completed",
        report_id=report_id,
        report_run_id=report_run_id,
        delivery_status=report_run.delivery_status,
        email_targets=len(email_targets),
        slack_targets=len(slack_targets),
        error_count=len(all_errors),
    )

    if not all_failed:
        return

    retryable = bool(email_errors) or any(failure.retryable for failure in slack_failures)
    if retryable:
        # Raise so the Temporal activity fails and retries fire per DELIVER_RETRY_POLICY.
        raise RuntimeError(f"All delivery targets failed for report run {report_run_id}: {'; '.join(all_errors)}")

    disable_undeliverable_report(report, report_run)
