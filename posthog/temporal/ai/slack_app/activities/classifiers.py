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
    group_by_runtime,
    is_slack_app_model_classifier_enabled,
)
from products.slack_app.backend.models import SlackThreadTaskMapping

logger = structlog.get_logger(__name__)

CLASSIFIER_THREAD_HISTORY_MESSAGES = 10
CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"


# The model-override and agent-directed classifiers both run on a reasoning model, which
# draws its reasoning from the same token budget as the reply. The reply is one short JSON
# object; the headroom is for the thinking in front of it, and a truncated turn falls back
# to the safe answer.
#
# The gateway client defaults to a 600s read and two retries, which is the right shape for
# a generation call and the wrong one here. Left unbounded these never get to fall back,
# because the activity's own deadline expires first. Bounding the retries matters as much
# as the timeout: the activity is sync, so a thread Temporal has stopped waiting on keeps
# blocking until the client itself returns.
MODEL_OVERRIDE_CLASSIFIER_MODEL = "gpt-5.6-luna"
MODEL_OVERRIDE_MAX_TOKENS = 2048
# One call per `@PostHog`, on the mention text alone. Measured mean is ~1.7s per call.
MODEL_OVERRIDE_TIMEOUT_SECONDS = 10.0
MODEL_OVERRIDE_MAX_RETRIES = 1

AGENT_DIRECTED_CLASSIFIER_MODEL = "gpt-5.6-luna"
AGENT_DIRECTED_MAX_TOKENS = 2048
# One call per reply in every thread the agent is working in, and its prompt carries the
# thread the override classifier's does not. The eval suite sees 3-9s on that shape, close
# enough to a 10s ceiling that the tail would drop instructions rather than misread them.
AGENT_DIRECTED_TIMEOUT_SECONDS = 20.0
AGENT_DIRECTED_MAX_RETRIES = 1


def classify_task_needs_repo(
    event_text: str,
    thread_messages: list[dict[str, str]],
) -> bool:
    """Classify whether a Slack conversation requires code repository access.

    Returns True if the task likely needs a repo (writing code, fixing bugs, PRs),
    False if it does not (analytics, data queries, PostHog config).

    Biased toward False: a false negative answers an analytics ask with no repo
    (recoverable — the user re-asks with code intent), while a false positive
    spends a discovery-agent sandbox run on "what's my DAU". Defaults to False
    on error for the same reason.
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
        # A failing test is code work, but it is named after the feature it covers, so the
        # product terms above would answer no-repo first. Keep these narrow: they match the
        # whole thread, and a bare "ci" would also catch confidence intervals.
        r"\bflak(?:y|e|es|iness)\b",
        r"\bmerge queue\b",
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
        "needs_repo.\n\n"
        "A failing, broken, or flaky CI run, test suite, or build is work in the team's own "
        "repository → needs_repo, including when the test is named after a PostHog feature "
        "('the experiment insight test is flaky'): the subject is their test, not our "
        "product.\n\n"
        "When in doubt, lean needs_repo=false — code-focused tasks usually carry "
        "explicit signals (file extensions, 'PR', 'commit', framework names, function or class "
        "names). Analytics, data, and configuration asks are the common case and should not send "
        "us hunting for a repository on a guess.\n\n"
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


def _agent_directed_response_format() -> ResponseFormatJSONSchema:
    """A strict JSON schema pinning the reply to a single boolean.

    The schema is what stops a reasoning model answering with its reasoning — prose parses
    to nothing, which reads the same as a refused call and silently drops the message.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "slack_app_agent_directed",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"agent_directed": {"type": "boolean"}},
                "required": ["agent_directed"],
                "additionalProperties": False,
            },
        },
    }


def classify_message_is_agent_directed(
    event_text: str,
    task_title: str,
    thread_history: list[dict[str, str]],
) -> bool:
    """Classify whether an untagged Slack thread reply is an instruction to the running
    PostHog Slack App, or people talking to each other.

    Deliberately defensive. Waking the agent is not private: it reacts in the channel, so a
    thread of humans discussing the work watches it interject on messages nobody addressed
    to it. A missed follow-up costs one ``@PostHog``, which the author would have typed
    anyway. So the bar is that the message reads as addressed to the agent — talking
    *about* the task, or about the agent, is not talking *to* it. Any failure returns
    ``False`` for the same reason.

    ``thread_history`` is the conversation so far (oldest first), as returned
    by ``collect_thread_messages`` — each entry is ``{"user", "text", "ts"}``.

    Whether the prompt holds that line is measured by
    ``products/slack_app/evals/eval_followup_classifier.py``.
    """
    stripped = event_text.strip()
    if re.fullmatch(r"(?:\s*:[a-z0-9_+-]+:\s*)+", stripped):
        logger.info("classify_message_is_agent_directed_heuristic_emoji_only", event_text=event_text)
        return False

    # Bound the number of lines and the per-line length to keep the prompt predictable.
    recent = thread_history[-CLASSIFIER_THREAD_HISTORY_MESSAGES:]
    history_block = "\n".join(f"{m.get('user', 'Unknown')}: {m.get('text', '')[:500]}" for m in recent) or "(empty)"

    prompt = (
        "The PostHog agent is working on a task in this Slack thread. People in the thread "
        "have stopped tagging it. Decide whether the latest message is an instruction to "
        "the agent that happens to omit the @mention.\n\n"
        "Answer true only when the message is addressed to the agent:\n"
        "  - An order or request to do something, with the agent as the only plausible "
        "audience ('also handle the empty case', 'skip the migration', 'open a PR for that "
        "too', 'try again with the other helper').\n"
        "  - A question put to the agent about its own work ('why did you skip the "
        "redesign commit?', 'does your PR cover the mobile breakpoint?').\n"
        "  - An answer to something the agent just asked in this thread.\n"
        "  - A correction of what the agent said or did ('no, the bug is in the handler, "
        "not the wrapper').\n\n"
        "Answer false for everything else. This is the common case, and the mistake to "
        "avoid — people talk about the work far more often than they talk to the agent:\n"
        "  - Opinions and discussion about the task or the product, addressed to the room "
        "('this needs a stronger label', 'it should probably live under settings', 'I've "
        "seen this set back and forth so much'). Relevant to the task is not the same as "
        "addressed to the agent.\n"
        "  - Talk about the agent in the third person ('why is the bot reacting to me?', "
        "'it keeps replying', 'is it supposed to do that?'). Being the topic is not being "
        "the audience.\n"
        "  - Conversation between humans — answering each other, tagging each other, "
        "deciding something among themselves.\n"
        "  - An instruction or request aimed at a named person, even with no @mention "
        "('sam go ahead and add yourself as the owner', 'jake, can you take this one'). A "
        "name in the thread is the audience; an order is not addressed to the agent just "
        "because it is phrased as one.\n"
        "  - A request only a person could carry out — joining a call, meeting a customer, "
        "updating an account in a system the agent has no access to — even when it says "
        "'you', and even when it directly follows something the agent said.\n"
        "  - Someone taking the work on themselves ('let me fix that', 'I'm on it', 'I'll "
        "take a look'). That stands the agent down; it is not a handoff to it.\n"
        "  - Acknowledgements, praise, and reactions ('thanks', 'lgtm', 'nice', '+1').\n"
        "  - Context dropped into the thread with no instruction attached — a link, a "
        "stack trace, a screenshot — unless the message asks the agent to act on it.\n"
        "  - Anything off-topic.\n\n"
        "When you are unsure, answer false. A missed instruction costs the author one "
        "@PostHog; a wrong wake-up makes the agent interrupt a conversation it was not "
        "part of, in public, where everyone sees it.\n\n"
        f"Task the agent is working on: {task_title or '(unknown)'}\n\n"
        f"Thread so far (oldest first):\n{history_block}\n\n"
        f"Latest message (from a human in this thread): {event_text}\n\n"
        'Answer with the one field, e.g. {"agent_directed": false}'
    )
    try:
        client = get_llm_client("slack_app_routing").with_options(
            timeout=AGENT_DIRECTED_TIMEOUT_SECONDS, max_retries=AGENT_DIRECTED_MAX_RETRIES
        )
        response = client.chat.completions.create(
            model=AGENT_DIRECTED_CLASSIFIER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=AGENT_DIRECTED_MAX_TOKENS,
            response_format=_agent_directed_response_format(),
        )
        # Tolerant parse on top of the schema on purpose: the gateway fronts several
        # providers and does not honour a response format identically on every route, so
        # a reply that arrives fenced still lands rather than dropping the message.
        parsed = extract_json_object(response.choices[0].message.content or "") or {}
        # Anything but the schema's boolean drops: a truthy string would invert the bias.
        return parsed.get("agent_directed") is True
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
    """The models on offer, as the runtime → models tree `group_by_runtime` defines."""
    lines = []
    for group in group_by_runtime(choices):
        lines.append(f"{group.label} runtime:")
        for choice in group.choices:
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

    Its other job is resolving the shorthand people actually type onto an id. Nobody
    writes ``gpt-5.6-sol``; they write "sol", or qualify it with the runtime or vendor
    it belongs to ("codex sol"), or name a family and leave the version off ("opus").

    Quality on both is measured by the eval suite in
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
        '  - "use fable for this one", "run this on opus 5", "do this with max effort", '
        '"investigate this on high".\n'
        "  - The instruction can sit alongside the actual request: 'use sonnet and fix "
        "the flaky checkout test'.\n\n"
        "Once — and only once — you have decided the message is such an instruction, "
        "resolve its shorthand to an id from the list. Nobody types a model id:\n"
        '  - A bare nickname is the model: "sol", "luna", "fable".\n'
        "  - A runtime or vendor in front of it is only a qualifier, and the name beside "
        'it is the answer: "codex sol" and "openai sol" are both the Sol id; "claude '
        'opus" and "anthropic opus" are both an Opus id.\n'
        '  - A family with no version means its newest listed member: "opus" is the '
        "highest-numbered Opus in the list, not the first one you see. Read the versions "
        "as decimals — 5 is newer than 4.8, not older.\n"
        '  - A runtime or vendor standing alone names no model: "run this on codex", '
        '"use anthropic" → null. A model id that happens to end in "codex" is a '
        "different thing, and needs its version said out loud to be chosen.\n\n"
        "Answer with nulls when a model or effort is merely part of the subject "
        "matter — this is the common mistake, so check for it:\n"
        '  - "add claude-fable-5 to our model picker" (a code change that names a model).\n'
        '  - "why is gpt-5 slower than opus in our evals?" (a question about models).\n'
        '  - "the opus rollout broke the dashboard" (a topic).\n'
        '  - "reasoning about this is hard" (the word, not a setting).\n'
        '  - "we tried sonnet on this last week and it kept timing out" (an account of a '
        "run that already happened, not an instruction for this one — past tense is the "
        "tell).\n\n"
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
    """Resolve the model a message asked for, or ``None`` to use saved preferences.

    Runs as its own activity rather than inside the activity that consumes it so the
    choice is recorded in workflow history once: both task creation and follow-up
    forwarding retry, and re-running a classifier there could hand the second attempt a
    different model than the first one announced. The workflow calls it once, above the
    point where the mention and follow-up paths diverge.

    Every message behind the flag reaches the classifier. A keyword pre-filter would
    save the Haiku call on the majority that name no model, but it also decides — on
    a substring match — which phrasings can ever steer a run, and that judgement
    belongs to the model reading the sentence, not to a word list. Blank text is not
    that judgement: there is no sentence to read.
    """
    if not input.event_text.strip():
        return None

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
        logger.info("slack_app_model_override_empty_catalogue", integration_id=integration.id)
        return None

    override = classify_slack_app_model_override(input.event_text, choices)
    if override is None:
        return None

    logger.info(
        "slack_app_model_override_classified",
        integration_id=integration.id,
        model=override.model,
        reasoning_effort=override.reasoning_effort,
    )
    return override
