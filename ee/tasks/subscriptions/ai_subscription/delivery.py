import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from markdown_it import MarkdownIt
from markdown_to_mrkdwn import SlackMarkdownConverter

from posthog.schema import AssistantHogQLQuery

from posthog.email import EmailMessage
from posthog.exceptions_capture import capture_exception
from posthog.models.integration import SlackIntegration
from posthog.models.subscription import Subscription, get_unsubscribe_token
from posthog.utils import absolute_uri

from ee.hogai.context.insight.query_executor import AssistantQueryExecutor
from ee.hogai.llm import MaxChatOpenAI
from ee.tasks.subscriptions.ai_subscription.prompts import AI_SUBSCRIPTION_SYNTHESIS_PROMPT
from ee.tasks.subscriptions.ai_subscription.schemas import EnrichedPromptSpec
from ee.tasks.subscriptions.ai_subscription.spec_generator import (
    DEFAULT_SYNTHESIS_MODEL,
    build_enriched_prompt,
    resolve_ai_model,
)
from ee.tasks.subscriptions.slack_subscriptions import UTM_TAGS_BASE, get_slack_integration_for_team

logger = structlog.get_logger(__name__)


_MARKDOWN_RENDERER = MarkdownIt("commonmark", {"breaks": True, "html": False})
_SLACK_CONVERTER = SlackMarkdownConverter()

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


def _compose_synthesis_human_message(spec: EnrichedPromptSpec, rendered_results: list[str]) -> str:
    results_block = "\n".join(rendered_results) if rendered_results else "_No query results were available._"
    return (
        f"<user_prompt>\n{spec.cleaned_prompt}\n</user_prompt>\n\n"
        f"<project_context>\n{spec.context_blob}\n</project_context>\n\n"
        f"Plan intent (system-provided, not user-controlled): {spec.plan.overall_intent}\n\n"
        f"<query_results>\n{results_block}\n</query_results>"
    )


async def _arun_plan(spec: EnrichedPromptSpec, subscription: Subscription) -> list[str]:
    executor = AssistantQueryExecutor(subscription.team, datetime.now(tz=UTC))

    async def run_step(step) -> str:
        try:
            query = AssistantHogQLQuery(query=step.hogql)
            formatted, _ = await executor.arun_and_format_query(query)
            return f"### {step.description}\n\n{formatted}"
        except Exception as exc:
            logger.warning(
                "ai_subscription.query_failed",
                subscription_id=subscription.id,
                step_description=step.description,
                exc_info=True,
            )
            capture_exception(exc, {"subscription_id": subscription.id, "stage": "query"})
            return f"### {step.description}\n\n_Query failed: {exc}_"

    return await asyncio.gather(*(run_step(step) for step in spec.plan.steps))


def generate_ai_subscription_markdown(subscription: Subscription) -> str:
    # Both LLM calls below pass `user=subscription.created_by` and MaxChatOpenAI
    # requires a non-None user. `created_by` is FK SET_NULL — fail fast if the
    # creator has been deleted so the activity captures a clear error.
    if subscription.created_by is None:
        from ee.tasks.subscriptions.ai_subscription.spec_generator import PromptRejectedError

        raise PromptRejectedError("AI subscription has no creator (created_by deleted); cannot deliver.")

    spec = build_enriched_prompt(subscription)
    rendered_results = asyncio.run(_arun_plan(spec, subscription))

    model_name = resolve_ai_model(subscription.ai_config, "model", DEFAULT_SYNTHESIS_MODEL)
    chat = MaxChatOpenAI(
        model=model_name,
        temperature=0.2,
        user=subscription.created_by,
        team=subscription.team,
        billable=False,
        posthog_properties={
            "feature": "ai_subscription",
            "stage": "synthesis",
            "subscription_id": subscription.id,
            "trace_id": str(uuid.uuid4()),
        },
    )

    result = chat.invoke(
        [
            ("system", AI_SUBSCRIPTION_SYNTHESIS_PROMPT),
            ("human", _compose_synthesis_human_message(spec, rendered_results)),
        ]
    )
    content = result.content if hasattr(result, "content") else str(result)
    return content if isinstance(content, str) else str(content)


def render_ai_email_html(markdown: str) -> str:
    return _MARKDOWN_RENDERER.render(markdown)


def send_email_ai_subscription_report(
    *,
    email: str,
    subscription: Subscription,
    markdown: str,
    rendered_html: str | None = None,
) -> None:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=email"
    html = rendered_html if rendered_html is not None else render_ai_email_html(markdown)
    title = subscription.title or "Your PostHog AI report"
    subscription_url = subscription.url or absolute_uri(
        f"/project/{subscription.team_id}/subscriptions/{subscription.id}"
    )
    unsubscribe_url = absolute_uri(f"/unsubscribe?token={get_unsubscribe_token(subscription, email)}&{utm_tags}")

    # Deterministic campaign_key so MessagingRecord dedups across Temporal activity
    # retries. `next_delivery_date` is the schedule-tick identifier; if it's None
    # (e.g. test_delivery, manually-triggered run), fall back to the subscription
    # id plus a per-day bucket so retries within the day still dedup.
    if subscription.next_delivery_date:
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


def send_slack_ai_subscription_report(
    *,
    subscription: Subscription,
    markdown: str,
) -> None:
    integration = get_slack_integration_for_team(subscription.team_id)
    if not integration:
        logger.warning("ai_subscription.slack_no_integration", subscription_id=subscription.id)
        return

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
            {"type": "section", "text": {"type": "mrkdwn", "text": "_See 🧵 for the rest of the report._"}}
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
                        "text": {"type": "plain_text", "text": "Manage Subscription"},
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
            slack_integration.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": section_text}}],
            )


__all__ = [
    "generate_ai_subscription_markdown",
    "render_ai_email_html",
    "send_email_ai_subscription_report",
    "send_slack_ai_subscription_report",
]
