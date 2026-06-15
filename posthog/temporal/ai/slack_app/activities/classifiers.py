import re
import json

import structlog
from temporalio import activity

from posthog.llm.gateway_client import get_llm_client
from posthog.models.integration import SlackIntegration
from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs
from posthog.temporal.common.utils import close_db_connections

from products.slack_app.backend.models import SlackThreadTaskMapping

logger = structlog.get_logger(__name__)

CLASSIFIER_THREAD_HISTORY_MESSAGES = 10


def classify_message_is_agent_directed(
    event_text: str,
    task_title: str,
    thread_history: list[dict[str, str]],
) -> bool:
    """Classify whether a Slack thread reply is addressing the running PostHog
    Slack App or pure side chatter between humans.

    The prompt leans toward forwarding when the message could plausibly help
    the agent or advance the task — a false positive is a single wasted turn
    the human can correct; a false negative forces the human to re-tag
    ``@PostHog`` to recover. Cheap pre-LLM heuristics still drop trivial
    messages (one word, emoji-only, very short) before paying for Haiku, and
    the function still returns ``False`` on a Haiku call error so a transient
    LLM outage can't fan out spurious forwards.

    ``thread_history`` is the conversation so far (oldest first), as returned
    by ``_collect_thread_messages`` — each entry is ``{"user", "text", "ts"}``.
    """
    stripped = event_text.strip()
    # Emoji-only / reaction-only replies are never agent-directed; drop before
    # paying for Haiku.
    if re.fullmatch(r"(?:\s*:[a-z0-9_+-]+:\s*)+", stripped):
        logger.info("classify_message_is_agent_directed_heuristic_emoji_only", event_text=event_text)
        return False

    # Render the tail of the thread for context. Bound the number of lines and
    # the per-line length to keep the prompt small and predictable.
    recent = thread_history[-CLASSIFIER_THREAD_HISTORY_MESSAGES:]
    history_block = "\n".join(f"{m.get('user', 'Unknown')}: {m.get('text', '')[:500]}" for m in recent) or "(empty)"

    prompt = (
        "You are routing replies in a Slack thread where the PostHog Slack App is "
        "currently working on a task. Decide whether the latest message is meant "
        "for the Slack App to read — instructions, corrections, follow-up asks, "
        "questions about the task, or context that helps it — versus pure side "
        "chatter between humans.\n\n"
        "Lean toward true when the message could plausibly help the Slack App or "
        "advance the task. Examples of agent_directed=true:\n"
        "  - Direct address ('@PostHog', 'agent, please…', 'bot, …').\n"
        "  - Instructions, corrections, or scope changes ('also handle the empty "
        "    case', 'use the new helper instead', 'actually skip the migration').\n"
        "  - Questions about the task or the Slack App's last update ('why did "
        "    you skip X?', 'what does this PR cover?', 'can you also do Y?').\n"
        "  - Task-relevant context (an error message, a URL, a file path, an "
        "    affected team/customer ID, a stack trace, a reproduction).\n"
        "  - Replies that elaborate on the human's earlier ask in this thread.\n\n"
        "Return agent_directed=false for clearly off-topic side chatter:\n"
        "  - Pure acknowledgements with no new info ('thanks', 'lgtm', 'nice', "
        "    'cool', emoji-only, '+1').\n"
        "  - Conversation clearly directed at another human (mentions another "
        "    user, answers their question, refers to people in third person).\n"
        "  - Off-topic chat unrelated to the task ('lunch in 5?', 'gn').\n\n"
        "When you're genuinely on the fence, prefer true — the human can correct "
        "the agent if it misreads, but a missed follow-up means the human has to "
        "re-tag @PostHog.\n\n"
        f"Task the Slack App is working on: {task_title or '(unknown)'}\n\n"
        f"Thread so far (oldest first):\n{history_block}\n\n"
        f"Latest message (from a human in this thread): {event_text}\n\n"
        'Respond with ONLY a JSON object: {"agent_directed": true} or {"agent_directed": false}'
    )
    try:
        client = get_llm_client("slack_app_routing")
        response = client.chat.completions.create(
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=64,
            temperature=0,
        )
        content = (response.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = content.strip("`").removeprefix("json").strip()
        parsed = json.loads(content)
        return bool(parsed.get("agent_directed", False))
    except Exception:
        logger.exception("classify_message_is_agent_directed_failed")
        return False


@activity.defn
@close_db_connections
def classify_untagged_followup_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    event_text: str,
) -> bool:
    """Decide whether an untagged thread reply should reach the agent.

    Runs the LLM + Slack thread-history fetch inside the workflow rather than
    the webhook handler so they're retriable under Temporal and don't block
    the Slack webhook's 3-second ack budget. Returns ``True`` to forward,
    ``False`` to drop. Conservative defaults: missing mapping → drop, history
    fetch failure → classify on text alone, classifier failure → drop.
    """
    from products.slack_app.backend.api import _collect_thread_messages

    try:
        mapping = SlackThreadTaskMapping.objects.select_related("task", "integration").get(
            integration_id=inputs.integration_id,
            channel=channel,
            thread_ts=thread_ts,
        )
    except SlackThreadTaskMapping.DoesNotExist:
        logger.info(
            "posthog_code_thread_message_mapping_gone",
            integration_id=inputs.integration_id,
            channel=channel,
            thread_ts=thread_ts,
        )
        return False

    integration = mapping.integration
    slack = SlackIntegration(integration)

    try:
        thread_history = _collect_thread_messages(slack, integration, channel, thread_ts, our_bot_id=None)
    except Exception:
        logger.exception(
            "posthog_code_thread_message_history_fetch_failed",
            channel=channel,
            thread_ts=thread_ts,
        )
        thread_history = []

    task_title = mapping.task.title if mapping.task and mapping.task.title else ""
    if classify_message_is_agent_directed(event_text, task_title, thread_history):
        return True

    logger.info(
        "posthog_code_thread_message_classified_chitchat",
        channel=channel,
        thread_ts=thread_ts,
        slack_user_id=slack_user_id,
    )
    return False
