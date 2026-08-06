import re

import structlog
from openai.types.shared_params import ResponseFormatJSONSchema
from pydantic import ValidationError
from temporalio import activity

from posthog.llm.gateway_client import get_llm_client
from posthog.llm.semantic_enrichment import extract_json_object
from posthog.models.integration import Integration, SlackIntegration
from posthog.temporal.ai.slack_app.types import (
    PostHogCodeSlackMentionWorkflowInputs,
    SlackAppModelOverride,
    SlackAppModelOverrideInput,
)
from posthog.temporal.common.utils import close_db_connections

from products.slack_app.backend.facade.run_preferences import (
    ModelChoice,
    available_model_choices,
    find_model_choice,
    is_slack_app_model_classifier_enabled,
)
from products.slack_app.backend.models import SlackThreadTaskMapping

logger = structlog.get_logger(__name__)

CLASSIFIER_THREAD_HISTORY_MESSAGES = 10
CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"
# The override classifier runs on a reasoning model, which draws its reasoning from the
# same token budget as the reply. The reply itself is one short JSON object; the headroom
# is for the thinking in front of it, and a truncated turn reads as an unusable reply and
# falls back to saved preferences.
MODEL_OVERRIDE_CLASSIFIER_MODEL = "gpt-5.6-luna"
MODEL_OVERRIDE_MAX_TOKENS = 2048
# The gateway client defaults to a 600s read and two retries of its own, which is the
# right shape for a generation call and the wrong one here: this classifier gates task
# creation, and its answer is optional — any failure falls back to saved preferences. Left
# unbounded it never gets to fall back, because the activity's own 600s deadline expires
# first and fails the mention outright. Bounding the retries matters as much as the
# deadline: the activity is sync, so a thread Temporal has stopped waiting on keeps
# blocking until the client itself returns. Measured mean is ~1.7s per call.
MODEL_OVERRIDE_TIMEOUT_SECONDS = 10.0
MODEL_OVERRIDE_MAX_RETRIES = 1


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
            model=CLASSIFIER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=64,
            temperature=0,
        )
        parsed = extract_json_object(response.choices[0].message.content or "") or {}
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
            model=CLASSIFIER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=64,
            temperature=0,
        )
        parsed = extract_json_object(response.choices[0].message.content or "") or {}
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


def _model_override_response_format(choices: tuple[ModelChoice, ...]) -> ResponseFormatJSONSchema:
    """A strict JSON schema pinning the reply to the result shape.

    The `model` enum is the point: it removes the classifier's ability to name a model
    this workspace can't drive, which the prompt could only ask for and
    ``find_model_choice`` could only catch after the fact.

    `reasoning_effort` stays an unconstrained string. Which efforts are valid depends on
    the model the run finally lands on, not on the catalogue-wide union, so it is settled
    once where the preferences are resolved — constraining it here would move that
    decision to the wrong place.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "slack_app_model_override",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "model": {"type": ["string", "null"], "enum": [*(c.model for c in choices), None]},
                    "reasoning_effort": {"type": ["string", "null"]},
                },
                "required": ["model", "reasoning_effort"],
                "additionalProperties": False,
            },
        },
    }


def _render_model_catalogue(choices: tuple[ModelChoice, ...]) -> str:
    lines = []
    for choice in choices:
        efforts = ", ".join(choice.supported_efforts) if choice.supported_efforts else "no effort setting"
        lines.append(f"- {choice.model} — {choice.label} (efforts: {efforts})")
    return "\n".join(lines)


def classify_slack_app_model_override(
    event_text: str,
    choices: tuple[ModelChoice, ...],
) -> SlackAppModelOverride | None:
    """Read a per-task model or reasoning-effort request out of a Slack mention.

    Returns ``None`` when the author asked for neither — which is the overwhelming
    majority of mentions, and the answer we fall back to on any parse, validation, or
    LLM failure. The cost of a miss is that the run uses the author's saved
    preferences, so every ambiguity resolves that way.

    The hard part is not spotting a model name; it is telling an instruction ("use
    fable for this") from subject matter ("add fable to the model picker"). The
    prompt is built around that distinction, and the schema restricts the answer to an
    id from ``choices``.

    Quality on that distinction is measured by the eval suite in
    ``products/slack_app/evals/eval_model_classifier.py`` — the unit tests around this
    function cover parsing and validation, not whether the prompt reads a sentence right.
    """
    prompt = (
        "You are routing a Slack message addressed to the PostHog agent. Decide whether "
        "the author asked for THIS task to run on a particular model or reasoning "
        "effort.\n\n"
        "Only these models can be selected — copy the id exactly as written:\n"
        f"{_render_model_catalogue(choices)}\n\n"
        "Name a model or effort only when the message instructs how to run this task:\n"
        '  - "use fable for this one", "run this on opus 5", "do this with max effort".\n'
        "  - The instruction can sit alongside the actual request: 'use sonnet and fix "
        "the flaky checkout test'.\n\n"
        "Answer with nulls when a model or effort is merely part of the subject "
        "matter — this is the common mistake, so check for it:\n"
        '  - "add claude-fable-5 to our model picker" (a code change that names a model).\n'
        '  - "why is gpt-5 slower than opus in our evals?" (a question about models).\n'
        '  - "the opus rollout broke the dashboard" (a topic).\n'
        '  - "reasoning about this is hard" (the word, not a setting).\n\n'
        "Rules for the fields:\n"
        "  - model: an id from the list above, or null if the author named no model (or "
        "named one that isn't listed).\n"
        "  - reasoning_effort: only when the author explicitly asks for an effort level, "
        "and only a value listed for that model. Otherwise null.\n"
        "  - An effort can be requested without a model, and a model without an effort.\n\n"
        "When you are unsure, answer with nulls — the author's saved default is the "
        "right thing to run.\n\n"
        f"Message: {event_text}\n\n"
        'Answer with the two fields, e.g. {"model": "claude-fable-5", "reasoning_effort": '
        '"high"} or {"model": null, "reasoning_effort": null}'
    )

    try:
        client = get_llm_client("slack_app_routing").with_options(
            timeout=MODEL_OVERRIDE_TIMEOUT_SECONDS, max_retries=MODEL_OVERRIDE_MAX_RETRIES
        )
        response = client.chat.completions.create(
            model=MODEL_OVERRIDE_CLASSIFIER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=MODEL_OVERRIDE_MAX_TOKENS,
            response_format=_model_override_response_format(choices),
        )
        # Tolerant parse on top of the schema on purpose: the gateway fronts several
        # providers and does not honour a response format identically on every route, so
        # a reply that arrives fenced still lands rather than failing the mention.
        parsed = extract_json_object(response.choices[0].message.content or "")
        # The reply has the same shape as the result, so it parses straight into it —
        # but the model is still the classifier's word, not ours, until checked against
        # the catalogue below.
        reply = SlackAppModelOverride.model_validate(parsed)
    except (ValidationError, ValueError):
        logger.info("slack_app_model_override_unusable_reply")
        return None
    except Exception:
        logger.exception("slack_app_model_override_classify_failed")
        return None

    choice = find_model_choice(reply.model, choices)
    if reply.model and choice is None:
        # The classifier was told to copy an id from the list; anything else is a
        # hallucination or a model we can't drive. Either way, don't act on it.
        logger.info("slack_app_model_override_unknown_model", requested_model=reply.model)

    # The effort rides through unchecked: which efforts a model supports depends on the
    # model the run finally lands on, so it is settled once, where the preferences are
    # resolved, rather than guessed against the catalogue-wide union here.
    if choice is None and not reply.reasoning_effort:
        return None
    return SlackAppModelOverride(model=choice.model if choice else None, reasoning_effort=reply.reasoning_effort)


@activity.defn
@close_db_connections
def classify_slack_app_model_override_activity(input: SlackAppModelOverrideInput) -> SlackAppModelOverride | None:
    """Resolve the model the mention asked for, or ``None`` to use saved preferences.

    Runs as its own activity rather than inside task creation so the choice is
    recorded in workflow history once: task creation retries, and re-running a
    classifier there could hand the second attempt a different model.

    Every mention behind the flag reaches the classifier. A keyword pre-filter would
    save the Haiku call on the majority that name no model, but it also decides — on
    a substring match — which phrasings can ever steer a run, and that judgement
    belongs to the model reading the sentence, not to a word list.
    """
    integration = Integration.objects.select_related("team").get(
        id=input.integration_id,
        kind="slack",
        integration_id=input.slack_team_id,
    )
    if not is_slack_app_model_classifier_enabled(integration):
        return None

    choices = available_model_choices()
    if not choices:
        # The gateway is the source of truth for what can run; with no catalogue we
        # cannot validate a request, and guessing is worse than doing nothing.
        logger.info("slack_app_model_override_empty_catalogue", integration_id=input.integration_id)
        return None

    override = classify_slack_app_model_override(input.event_text, choices)
    if override is None:
        return None

    logger.info(
        "slack_app_model_override_classified",
        integration_id=input.integration_id,
        model=override.model,
        reasoning_effort=override.reasoning_effort,
    )
    return override
