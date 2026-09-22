import re
from pathlib import Path

import structlog
from openai.types.shared_params import ResponseFormatJSONSchema
from pydantic import BaseModel, ValidationError
from temporalio import activity

from posthog.llm.gateway_client import build_anthropic_client, build_openai_client
from posthog.llm.semantic_enrichment import extract_json_object
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.repo_routing_rule import RepoRoutingRule
from posthog.models.user import User
from posthog.temporal.ai.slack_app.types import (
    PostHogCodeSlackMentionWorkflowInputs,
    SlackAppModelOverride,
    SlackAppModelOverrideInput,
    SlackAppProjectRoute,
    SlackAppProjectRouteInput,
)
from posthog.temporal.common.utils import close_db_connections

from products.slack_app.backend.facade.run_preferences import (
    ModelChoice,
    available_model_choices,
    find_model_choice,
    group_by_runtime,
)
from products.slack_app.backend.models import SlackThreadTaskMapping
from products.slack_app.backend.prompt_templates import PromptTemplates
from products.slack_app.backend.services.integration_resolver import format_project_candidate_list, routable_projects
from products.slack_app.backend.services.slack_messages import SlackThreadMessage
from products.slack_app.backend.services.slack_user_info import find_addressed_bot_user_id

logger = structlog.get_logger(__name__)

prompts = PromptTemplates(Path(__file__).parent / "prompts")

CLASSIFIER_THREAD_HISTORY_MESSAGES = 10
CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"

# Every classifier here shares `ai_product="slack_app_routing"`, so the captured generation
# carries this property to say which one of them made the call. An online evaluation scopes
# itself with it; without it a judge would grade all four.
CLASSIFIER_PROPERTY = "slack_app_classifier"


# The model-override and agent-directed classifiers both run on a reasoning model, which
# draws its reasoning from the same token budget as the reply. The reply is one short JSON
# object; the headroom is for the thinking in front of it, and a truncated turn falls back
# to the safe answer. Reasoning-class is also why the cap rides on `max_completion_tokens`:
# the chat-completions route rejects `max_tokens` outright.
#
# The gateway client defaults to a 600s read and two retries, which is the right shape for
# a generation call and the wrong one here. Left unbounded these never get to fall back,
# because the activity's own deadline expires first. Bounding the retries matters as much
# as the timeout: the activity is sync, so a thread Temporal has stopped waiting on keeps
# blocking until the client itself returns.
MODEL_OVERRIDE_CLASSIFIER_MODEL = "gpt-5.6-luna"
MODEL_OVERRIDE_MAX_COMPLETION_TOKENS = 2048
# One call per `@PostHog`, on the mention text alone. Measured mean is ~1.7s per call.
MODEL_OVERRIDE_TIMEOUT_SECONDS = 10.0
MODEL_OVERRIDE_MAX_RETRIES = 1

# Same shape of call as the model override, so it takes the same bounds — including the
# cap riding on `max_completion_tokens`. The reasoning-class chat-completions route
# rejects `max_tokens` outright, and the classifier would swallow that into its fallback.
PROJECT_ROUTE_CLASSIFIER_MODEL = "gpt-5.6-luna"
PROJECT_ROUTE_MAX_COMPLETION_TOKENS = 2048
PROJECT_ROUTE_TIMEOUT_SECONDS = 10.0
PROJECT_ROUTE_MAX_RETRIES = 1

AGENT_DIRECTED_CLASSIFIER_MODEL = "gpt-5.6-luna"
AGENT_DIRECTED_MAX_COMPLETION_TOKENS = 2048
# One call per reply in every thread the agent is working in, and its prompt carries the
# thread the override classifier's does not. The eval suite sees 3-9s on that shape, close
# enough to a 10s ceiling that the tail would drop instructions rather than misread them.
AGENT_DIRECTED_TIMEOUT_SECONDS = 20.0
AGENT_DIRECTED_MAX_RETRIES = 1


def team_routing_rule_lines(team_id: int, candidate_repos: set[str] | None = None) -> list[str]:
    """The team's routing rules rendered one per line for the needs-repo classifier prompt.

    ``candidate_repos`` is the lowercased set of repositories selection can still pick.
    When given, rules pointing outside it are dropped: a stale rule (repo disconnected or
    archived) would disable the product-term short-circuit and spend an agent run on a
    pick that selection later rejects anyway.
    """
    rules = RepoRoutingRule.objects.filter(team_id=team_id).order_by("priority", "id")
    matched = [rule for rule in rules if candidate_repos is None or rule.repository.lower() in candidate_repos]
    return [
        f"- {rule.prompt_text} → {rule.repository.lower()}" for rule in matched[: RepoRoutingRule.MAX_RULES_PER_TEAM]
    ]


def classify_task_needs_repo(
    event_text: str,
    thread_messages: list[SlackThreadMessage],
    routing_rules: list[str] | None = None,
) -> bool:
    """Classify whether a Slack conversation requires code repository access.

    Returns True if the task likely needs a repo (writing code, fixing bugs, PRs),
    False if it does not (analytics, data queries, PostHog config).

    Biased toward False: a false negative answers an analytics ask with no repo
    (recoverable — the user re-asks with code intent), while a false positive
    spends a discovery-agent sandbox run on "what's my DAU". Defaults to False
    on error for the same reason.

    ``routing_rules`` is the team's configured repo routing rules (see
    ``team_routing_rule_lines``). A rule claims a kind of request for a repository the
    team owns, and only the LLM can tell whether this request matches one, so any
    configured rule disables the product-term short-circuit below and rides along in
    the prompt. Without this, a rule mentioning a product term ("our dashboards live
    in org/dashboards") could never fire: the heuristic answered no-repo before the
    rules were ever read.
    """
    conversation = "\n".join(f"{msg.user}: {msg.text}" for msg in thread_messages)
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

    if (
        not routing_rules
        and any(term in normalized for term in product_debug_terms)
        and not any(re.search(pattern, normalized) for pattern in explicit_code_patterns)
    ):
        logger.info("slack_app_classify_task_needs_repo_heuristic_non_repo", event_text=event_text)
        return False

    prompt = prompts.render(
        "task_needs_repo",
        routing_rules=routing_rules,
        conversation=conversation,
        event_text=event_text,
    )
    try:
        # The Go gateway refuses a Claude model on chat completions.
        client = build_anthropic_client(
            product="slack_app_routing",
            ai_product="slack_app_routing",
            properties={CLASSIFIER_PROPERTY: "task_needs_repo"},
        )
        response = client.messages.create(
            model=CLASSIFIER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=64,
            temperature=0,
        )
        reply = "".join(block.text for block in response.content if block.type == "text")
        parsed = extract_json_object(reply) or {}
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
@close_db_connections
def classify_posthog_code_task_needs_repo_activity(
    event_text: str,
    thread_messages: list[SlackThreadMessage],
    inputs: PostHogCodeSlackMentionWorkflowInputs | None = None,
) -> bool:
    """Classify with the team's routing rules loaded from ``inputs``.

    ``inputs`` sits last and optional for payload compatibility: activity tasks queued
    by pre-deploy workflow code carry only the first two payloads, and a required
    leading parameter would make them unbindable on a new worker. Such tasks classify
    without routing rules, which is the pre-deploy behavior.
    """
    # Circular import: products.slack_app.backend.api imports this package at module scope.
    from products.slack_app.backend.api import _get_full_repo_names  # noqa: PLC0415

    if inputs is None:
        return classify_task_needs_repo(event_text, thread_messages)

    integration = Integration.objects.get(
        id=inputs.integration_id,
        kind="slack",
        integration_id=inputs.slack_team_id,
    )
    # Filter rules to repos the mentioner can reach, matching what selection accepts for
    # this mention. An empty list means the lookup resolved nothing (the cascade would
    # have stopped such a mention already), so treat it as unknown rather than dropping
    # every rule.
    connected = {repo.lower() for repo in _get_full_repo_names(integration, user_id=inputs.user_id)}
    routing_rules = team_routing_rule_lines(integration.team_id, candidate_repos=connected or None)
    return classify_task_needs_repo(event_text, thread_messages, routing_rules=routing_rules)


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
    thread_history: list[SlackThreadMessage],
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
    by ``collect_thread_messages``.

    Whether the prompt holds that line is measured by
    ``products/slack_app/evals/eval_followup_classifier.py``.
    """
    stripped = event_text.strip()
    if re.fullmatch(r"(?:\s*:[a-z0-9_+-]+:\s*)+", stripped):
        logger.info("classify_message_is_agent_directed_heuristic_emoji_only", event_text=event_text)
        return False

    # Bound the number of lines and the per-line length to keep the prompt predictable.
    recent = thread_history[-CLASSIFIER_THREAD_HISTORY_MESSAGES:]
    history_block = "\n".join(f"{m.user or 'Unknown'}: {m.text[:500]}" for m in recent) or "(empty)"

    prompt = prompts.render(
        "message_is_agent_directed",
        task_title=task_title or "(unknown)",
        thread_history=history_block,
        event_text=event_text,
    )
    try:
        client = build_openai_client(
            product="slack_app_routing",
            ai_product="slack_app_routing",
            properties={CLASSIFIER_PROPERTY: "agent_directed"},
        ).with_options(timeout=AGENT_DIRECTED_TIMEOUT_SECONDS, max_retries=AGENT_DIRECTED_MAX_RETRIES)
        response = client.chat.completions.create(
            model=AGENT_DIRECTED_CLASSIFIER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=AGENT_DIRECTED_MAX_COMPLETION_TOKENS,
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
    ``False`` to drop. Conservative defaults: missing mapping → drop, a reply
    that tags another app → drop, history fetch failure → classify on text
    alone, classifier failure → drop.
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

    # Asked before the history fetch and the model call, because reading the reply cannot
    # answer it.
    addressed_bot_user_id = find_addressed_bot_user_id(slack, integration, event_text)
    if addressed_bot_user_id:
        logger.info(
            "posthog_code_thread_message_addressed_to_another_app",
            channel=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
            addressed_bot_user_id=addressed_bot_user_id,
        )
        return False

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
    prompt = prompts.render(
        "model_override",
        model_catalogue=_render_model_catalogue(choices),
        event_text=event_text,
    )

    try:
        client = build_openai_client(
            product="slack_app_routing",
            ai_product="slack_app_routing",
            properties={CLASSIFIER_PROPERTY: "model_override"},
        ).with_options(timeout=MODEL_OVERRIDE_TIMEOUT_SECONDS, max_retries=MODEL_OVERRIDE_MAX_RETRIES)
        response = client.chat.completions.create(
            model=MODEL_OVERRIDE_CLASSIFIER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=MODEL_OVERRIDE_MAX_COMPLETION_TOKENS,
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

    Every message reaches the classifier. A keyword pre-filter would
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


def _project_route_response_format(projects: list[Integration]) -> ResponseFormatJSONSchema:
    """A strict JSON schema pinning the reply to one id from ``projects``.

    The enum is what stops the classifier naming a project this mentioner cannot reach.
    `routable_projects` bounds the list by access, and that bound only reaches the model
    through this field.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "slack_app_project_route",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "project_id": {"type": ["integer", "null"], "enum": [*(p.team_id for p in projects), None]},
                },
                "required": ["project_id"],
                "additionalProperties": False,
            },
        },
    }


class _ProjectRouteReply(BaseModel):
    project_id: int | None = None


def classify_slack_app_project_route(
    event_text: str, projects: list[Integration], default: Integration | None = None
) -> Integration | None:
    """Read the project a mention asked to be answered from, out of its text.

    ``default`` is the project the run is already on. It heads the list the model is
    shown and is marked there, so that staying put is a visible choice rather than the
    absence of one.

    Returns ``None`` when the author named none, which is the overwhelming majority of
    mentions, and on a reply this cannot parse.

    A gateway failure raises instead of returning ``None``. The activity turns that into
    the same fallback, so production behaviour is unchanged; the eval suite calls this
    function directly, and a swallowed failure there is indistinguishable from a clean
    "no project" — it would score a dead gateway as a pass on every negative case.

    It takes the opposite rule to the model classifier: a model named as the subject of a
    question is never an instruction, while a project named as the subject usually is
    where the answer has to come from, because that is where the data lives. Quality on
    that is measured by ``products/slack_app/evals/eval_project_classifier.py``.
    """
    # Named to the model by id rather than by a marker on its line: a team may be called
    # anything, including whatever that marker would have been.
    if default is not None and not any(p.id == default.id for p in projects):
        default = None
    prompt = prompts.render(
        "project_route",
        projects=format_project_candidate_list(projects, first=default),
        default_id=default.team_id if default is not None else None,
        event_text=event_text,
    )

    try:
        client = build_openai_client(
            product="slack_app_routing",
            ai_product="slack_app_routing",
            properties={CLASSIFIER_PROPERTY: "project_route"},
        ).with_options(timeout=PROJECT_ROUTE_TIMEOUT_SECONDS, max_retries=PROJECT_ROUTE_MAX_RETRIES)
        response = client.chat.completions.create(
            model=PROJECT_ROUTE_CLASSIFIER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=PROJECT_ROUTE_MAX_COMPLETION_TOKENS,
            response_format=_project_route_response_format(projects),
        )
        # Tolerant parse on top of the schema, matching the model-override classifier:
        # the gateway does not honour a response format identically on every route.
        parsed = extract_json_object(response.choices[0].message.content or "")
        reply = _ProjectRouteReply.model_validate(parsed)
    except (ValidationError, ValueError):
        logger.info("slack_app_project_route_unusable_reply")
        return None

    if reply.project_id is None:
        return None
    chosen = next((p for p in projects if p.team_id == reply.project_id), None)
    if chosen is None:
        # The classifier was told to copy an id from the list; anything else is a
        # hallucination or a project this mentioner cannot open.
        logger.info("slack_app_project_route_unknown_project", requested_team_id=reply.project_id)
    return chosen


@activity.defn
@close_db_connections
def classify_slack_app_project_route_activity(input: SlackAppProjectRouteInput) -> SlackAppProjectRoute | None:
    """Resolve the project a mention asked for, or ``None`` to stay on the resolved one.

    The workflow calls this only for a message that opens a thread. A task, its thread
    mapping and its run all belong to one project, so a reply cannot move the thread.
    """
    if not input.event_text.strip():
        return None
    # Cheapest gate first, and the one that answers most workspaces. Everything below is
    # two queries and an access scan, and a workspace connected to one project has
    # nothing to route between however they come out.
    if Integration.objects.filter(kind="slack", integration_id=input.slack_team_id).count() < 2:
        return None

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=input.integration_id,
        kind="slack",
        integration_id=input.slack_team_id,
    )
    user = User.objects.filter(id=input.user_id).first()
    if user is None:
        return None

    projects = routable_projects(
        slack_team_id=input.slack_team_id,
        slack_user_id=input.slack_user_id,
        user=user,
    )
    if not projects:
        return None

    try:
        chosen = classify_slack_app_project_route(input.event_text, projects, default=integration)
    except Exception:
        # The fallback boundary: a mention we cannot classify stays on the project
        # routing already resolved, which is what it would have done anyway.
        logger.exception("slack_app_project_route_classify_failed")
        return None
    # A message naming the project the run was already going to use asked for nothing.
    if chosen is None or chosen.id == integration.id:
        return None

    logger.info(
        "slack_app_project_route_classified",
        integration_id=integration.id,
        routed_integration_id=chosen.id,
        project_candidate_count=len(projects),
    )
    return SlackAppProjectRoute(integration_id=chosen.id)
