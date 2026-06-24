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


def classify_task_needs_repo(
    event_text: str,
    thread_messages: list[dict[str, str]],
) -> bool:
    """Classify whether a Slack conversation requires code repository access.

    Returns True if the task likely needs a repo (writing code, fixing bugs, PRs),
    False if it does not (analytics, data queries, PostHog config).

    Biased toward False: a false negative answers an analytics ask with no repo
    (recoverable — the user re-asks with code intent), while a false positive
    walls the user behind the Connect-GitHub gate even for "what's my DAU".
    Defaults to False on error for the same reason.
    """
    conversation = "\n".join(f"{msg['user']}: {msg['text']}" for msg in thread_messages)
    normalized = f"{conversation}\nLatest message: {event_text}".lower()

    # Substring match: keep the shortest form that uniquely identifies the
    # concept without colliding with code-review vocabulary. Plurals are used
    # only when the singular substring-matches a common non-analytics word
    # (e.g. `event` → `eventually`, `person` → `personal`).
    product_debug_terms = (
        # Product/config debugging
        "automation",
        "destination",
        "posthog ai feedback",
        "feature flag",
        "experiment",
        "survey",
        "dashboard",
        "insight",
        "recording",
        "mcp",
        "webhook",
        # Analytics primitives and data asks
        "events",
        "persons",
        "cohort",
        "trend",
        "funnel",
        "retention",
        "hogql",
        "replay",
        "breakdown",
        "dau",
        "mau",
        "error tracking",
        "llm analytics",
        "revenue",
        "marketing analytics",
    )
    explicit_code_patterns = (
        r"\brepository\b",
        r"\brepo\b",
        r"\bpull request\b",
        r"\bopen a pr\b",
        r"\bcreate a pr\b",
        r"\bcommit\b",
        r"\bbranch\b",
        r"\bmodify code\b",
        r"\bchange code\b",
        r"\bwrite code\b",
        r"\bimplement\b",
        r"\.py\b",
        r"\.ts\b",
        r"\.tsx\b",
        r"\.js\b",
        r"\bserializer\b",
        r"\bviewset\b",
        r"\bmigration\b",
    )

    if any(term in normalized for term in product_debug_terms) and not any(
        re.search(pattern, normalized) for pattern in explicit_code_patterns
    ):
        logger.info("slack_app_classify_task_needs_repo_heuristic_non_repo", event_text=event_text)
        return False

    prompt = (
        "You are a task classifier. Given a Slack conversation, determine whether the task "
        "requires access to a code repository (e.g. writing code, fixing bugs, creating PRs, "
        "reviewing code, modifying files) or NOT (e.g. answering questions about analytics, "
        "querying data, PostHog configuration, general knowledge questions, planning, or "
        "investigating product behavior in a PostHog workspace using MCP/tools).\n\n"
        "Return needs_repo=false for tasks that are primarily about debugging or investigating "
        "automations, destinations, feature flags, experiments, surveys, dashboards, insights, "
        "recordings, traces, or Slack integrations inside PostHog, unless the user explicitly "
        "asks to change code, open a PR, edit files, or work in a specific repository.\n\n"
        "A complaint about something the team's own app, site, or SDK does (crashes, broken pages, "
        "wrong rendering, slow loads of a site they ship) is a code change in a repo they own → "
        "needs_repo. But complaints about PostHog itself as a product (its dashboards hanging, "
        "product pages loading slowly, UI bugs in PostHog screens) are SaaS product issues, not "
        "the team's code → no_repo. Important exception: 'wrong data', 'missing events', or "
        "'numbers look off' in PostHog usually means the team's tracking code is broken (wrong "
        "event names, identification logic, SDK setup) — that's a code fix in their repo → "
        "needs_repo. When in doubt, lean needs_repo=false — code-focused tasks usually carry "
        "explicit signals (file extensions, 'PR', 'commit', framework names, function or class "
        "names). Analytics, data, and configuration asks are the common case and should not be "
        "walled behind a Connect-GitHub prompt on a guess.\n\n"
        f"Conversation:\n{conversation}\n\n"
        f"Latest message: {event_text}\n\n"
        'Respond with ONLY a JSON object: {{"needs_repo": true}} or {{"needs_repo": false}}'
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
        # Haiku occasionally stringifies the bool ({"needs_repo": "false"}).
        # bool("false") is True, which would flip the defensive bias — handle
        # strings explicitly and treat any other unexpected shape as False.
        value = parsed.get("needs_repo", False)
        if isinstance(value, str):
            return value.strip().lower() == "true"
        return value is True
    except Exception:
        logger.exception("slack_app_classify_task_needs_repo_failed")
        return False


@activity.defn
def classify_posthog_code_task_needs_repo_activity(
    event_text: str,
    thread_messages: list[dict[str, str]],
) -> bool:
    return classify_task_needs_repo(event_text, thread_messages)


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
    by ``collect_thread_messages`` — each entry is ``{"user", "text", "ts"}``.
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
    from products.slack_app.backend.services.slack_messages import cached_collect_thread_messages

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
        # Cached: the next activity in this workflow run (the forwarder) re-fetches the
        # same thread to compute its diff; a cache hit there avoids a second Slack call.
        thread_history = cached_collect_thread_messages(slack, integration, channel, thread_ts, our_bot_id=None)
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
