from datetime import UTC, datetime

import nh3
import structlog
from markdown_it import MarkdownIt
from markdown_to_mrkdwn import SlackMarkdownConverter

from posthog.email import EmailMessage
from posthog.exceptions_capture import capture_exception
from posthog.models.integration import SlackIntegration
from posthog.models.subscription import Subscription, get_unsubscribe_token
from posthog.utils import absolute_uri

from ee.hogai.ai_reports import generate_ai_report
from ee.tasks.subscriptions.ai_subscription.spec_generator import PromptRejectedError, frequency_to_window_days
from ee.tasks.subscriptions.slack_subscriptions import UTM_TAGS_BASE, get_slack_integration_for_team

logger = structlog.get_logger(__name__)


_MARKDOWN_RENDERER = MarkdownIt("commonmark", {"breaks": True, "html": False}).enable("table")
_SLACK_CONVERTER = SlackMarkdownConverter()

# Defense-in-depth on top of `html=False` in markdown-it: explicitly allow only the
# tags commonmark emits, strip everything else. Protects against a markdown-it
# regression or a future synthesis-prompt change that leaks raw HTML through.
_ALLOWED_EMAIL_TAGS = {
    "a",
    "p",
    "br",
    "hr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "b",
    "i",
    "code",
    "pre",
    "blockquote",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
}
_ALLOWED_EMAIL_ATTRS = {"a": {"href", "title"}}

# Slack's hard limit is 3000 chars per section block; keep margin for safety.
SLACK_MRKDWN_SECTION_LIMIT = 2900


def _split_into_slack_sections(text: str, limit: int = SLACK_MRKDWN_SECTION_LIMIT) -> list[str]:
    """Split a long markdown body into chunks ≤ limit chars, breaking on paragraph boundaries where possible."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        # Prefer to break on the last double-newline before limit.
        cut = remaining.rfind("\n\n", 0, limit)
        if cut == -1:
            cut = remaining.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def generate_ai_subscription_markdown(subscription: Subscription) -> str:
    """Subscription-flavoured wrapper around :func:`generate_ai_report` — just unpacks
    the persisted row and forwards to the shared pipeline."""
    # `created_by` is FK SET_NULL; the shared primitive requires a non-None user.
    if subscription.created_by is None:
        raise PromptRejectedError("AI subscription has no creator (created_by deleted); cannot deliver.")

    return generate_ai_report(
        team=subscription.team,
        user=subscription.created_by,
        prompt=subscription.prompt,
        window_days=frequency_to_window_days(subscription.frequency),
        ai_config=subscription.ai_config,
        trace_correlation_id=subscription.id,
    )


def render_ai_email_html(markdown: str) -> str:
    rendered = _MARKDOWN_RENDERER.render(markdown)
    return nh3.clean(rendered, tags=_ALLOWED_EMAIL_TAGS, attributes=_ALLOWED_EMAIL_ATTRS)


def send_email_ai_subscription_report(
    *,
    email: str,
    subscription: Subscription,
    markdown: str,
    rendered_html: str | None = None,
    delivery_run_id: str | None = None,
) -> None:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=email"
    html = rendered_html if rendered_html is not None else render_ai_email_html(markdown)
    title = subscription.title or "Your PostHog AI report"
    subscription_url = subscription.url or absolute_uri(
        f"/project/{subscription.team_id}/subscriptions/{subscription.id}"
    )
    unsubscribe_url = absolute_uri(f"/unsubscribe?token={get_unsubscribe_token(subscription, email)}&{utm_tags}")

    # Deterministic campaign_key so MessagingRecord dedups across Temporal activity
    # retries. Preferred input is the Temporal workflow_run_id: it's stable across
    # activity retries within one workflow run but unique per run, so a scheduled
    # tick dedups its own retries while a fresh "Test delivery" click (new workflow
    # run) gets a fresh key and actually sends. `next_delivery_date` is used as a
    # fallback when called outside Temporal (tests, management commands); a per-day
    # bucket is the last resort for newly created subs that have neither.
    if delivery_run_id:
        campaign_key = f"ai_subscription_report_{subscription.id}_{delivery_run_id}"
    elif subscription.next_delivery_date:
        campaign_key = f"ai_subscription_report_{subscription.id}_{subscription.next_delivery_date.isoformat()}"
    else:
        campaign_key = f"ai_subscription_report_{subscription.id}_{datetime.now(tz=UTC).date().isoformat()}"

    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f"PostHog AI report - {title}",
        template_name="ai_subscription_report",
        template_context={
            "title": title,
            "rendered_html": html,
            "subscription_url": f"{subscription_url}?{utm_tags}",
            "unsubscribe_url": unsubscribe_url,
        },
    )
    message.add_recipient(email=email)
    message.send(send_async=False)


class SlackIntegrationMissingError(RuntimeError):
    """Raised when an AI subscription's Slack integration can't be resolved at send time."""


def send_slack_ai_subscription_report(
    *,
    subscription: Subscription,
    markdown: str,
) -> None:
    # Respect the integration the user explicitly attached to this subscription;
    # only fall back to the team-wide first match when none is configured (matches
    # the non-AI Slack delivery path). Raise on missing so the activity can
    # auto-disable instead of recording a phantom "success".
    integration = subscription.integration
    if integration is not None and integration.kind != "slack":
        logger.warning(
            "ai_subscription.slack_invalid_integration_kind",
            subscription_id=subscription.id,
            integration_id=integration.id,
            kind=integration.kind,
        )
        integration = None
    if integration is None:
        integration = get_slack_integration_for_team(subscription.team_id)
    if not integration:
        raise SlackIntegrationMissingError(
            f"No Slack integration available for subscription {subscription.id} (team {subscription.team_id})"
        )

    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=slack"
    channel = subscription.target_value.split("|")[0]
    mrkdwn_body = _SLACK_CONVERTER.convert(markdown)
    sections = _split_into_slack_sections(mrkdwn_body)
    title = subscription.title or "Your PostHog AI report"

    main_blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": sections[0]}},
    ]
    if len(sections) > 1:
        main_blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "_See thread for the rest of the report._"}}
        )

    subscription_url = subscription.url or absolute_uri(
        f"/project/{subscription.team_id}/subscriptions/{subscription.id}"
    )
    main_blocks.extend(
        [
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Manage subscription"},
                        "url": f"{subscription_url}?{utm_tags}",
                    }
                ],
            },
        ]
    )

    slack_integration = SlackIntegration(integration)
    response = slack_integration.client.chat_postMessage(channel=channel, blocks=main_blocks, text=title)
    thread_ts = response.get("ts")

    if thread_ts and len(sections) > 1:
        for section_text in sections[1:]:
            # Per-thread-post failures shouldn't raise: the main message is already
            # delivered, and re-raising would trigger a Temporal retry that re-posts
            # the main message (Slack has no idempotency key the way email's
            # MessagingRecord does). Capture + continue.
            try:
                slack_integration.client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": section_text}}],
                )
            except Exception as exc:
                logger.warning(
                    "ai_subscription.slack_thread_post_failed",
                    subscription_id=subscription.id,
                    thread_ts=thread_ts,
                    exc_info=True,
                )
                capture_exception(exc, {"subscription_id": subscription.id, "stage": "slack_thread"})


__all__ = [
    "generate_ai_subscription_markdown",
    "render_ai_email_html",
    "send_email_ai_subscription_report",
    "send_slack_ai_subscription_report",
]
