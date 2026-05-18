import re
from datetime import UTC, datetime

import structlog

from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team
from posthog.models.subscription import Subscription
from posthog.schema import CachedTeamTaxonomyQueryResponse, TeamTaxonomyQuery
from posthog.temporal.subscriptions.prompt_sanitization import sanitize_core_memory_text, sanitize_user_text

from ee.hogai.llm import MaxChatOpenAI
from ee.tasks.subscriptions.ai_subscription.prompts import PLAN_GENERATION_PROMPT
from ee.tasks.subscriptions.ai_subscription.schemas import EnrichedPromptSpec, QueryPlan

logger = structlog.get_logger(__name__)


PROMPT_MAX_LENGTH = 4000
EVENT_NAMES_SAMPLE_LIMIT = 20
EVENT_NAME_MAX_LENGTH = 120

DEFAULT_PLANNER_MODEL = "gpt-4.1-mini"
DEFAULT_SYNTHESIS_MODEL = "gpt-4.1-mini"
# Whitelist of models a user can opt their subscription into via `ai_config`.
# Without this, any authenticated user could PATCH `ai_config: {"model": ...}` and
# force scheduled deliveries to use an arbitrarily expensive model.
ALLOWED_AI_MODELS = frozenset({"gpt-4.1-mini", "gpt-4.1-nano", "gpt-4.1"})


def resolve_ai_model(ai_config: dict | None, key: str, default: str) -> str:
    requested = (ai_config or {}).get(key)
    if isinstance(requested, str) and requested in ALLOWED_AI_MODELS:
        return requested
    return default

# Layered on top of `sanitize_core_memory_text` (which strips invisible chars and structural
# LLM markers like `<system>`). Best-effort only; the real defenses are response-side
# (markdown rendering with html=False, Slack mrkdwn).
INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore\s+(all\s+|previous\s+|the\s+above\s+)?instructions"),
    re.compile(r"(?i)you\s+are\s+now\s+"),
    re.compile(r"(?i)system\s+prompt\s*:"),
    re.compile(r"```\s*system", re.IGNORECASE),
]


_FREQUENCY_WINDOW_DAYS = {
    Subscription.SubscriptionFrequency.HOURLY: 1,
    Subscription.SubscriptionFrequency.DAILY: 1,
    Subscription.SubscriptionFrequency.WEEKLY: 7,
    Subscription.SubscriptionFrequency.MONTHLY: 30,
    Subscription.SubscriptionFrequency.YEARLY: 365,
}


class PromptRejectedError(ValueError):
    pass


def sanitize_prompt(raw: str | None) -> str:
    if not raw or not raw.strip():
        raise PromptRejectedError("Prompt is empty.")
    if len(raw.strip()) > PROMPT_MAX_LENGTH:
        raise PromptRejectedError(f"Prompt exceeds {PROMPT_MAX_LENGTH} characters.")

    cleaned = sanitize_core_memory_text(raw, max_len=PROMPT_MAX_LENGTH)
    if not cleaned:
        raise PromptRejectedError("Prompt is empty.")

    for pattern in INJECTION_PATTERNS:
        if pattern.search(cleaned):
            raise PromptRejectedError("Prompt contains content that cannot be processed.")

    return cleaned


def _window_days_for(frequency: str) -> int:
    return _FREQUENCY_WINDOW_DAYS.get(frequency, 7)


def _top_event_names(team: Team, limit: int) -> list[str]:
    query = TeamTaxonomyQuery(limit=limit)
    response = TeamTaxonomyQueryRunner(query, team).run(
        ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS,
    )
    if not isinstance(response, CachedTeamTaxonomyQueryResponse):
        return []
    # Event names are user-controlled (project tokens are public — anyone can fire
    # events with arbitrary names). Sanitize so an attacker can't seed the LLM
    # context with prompt-injection payloads via crafted event names.
    sanitized = (sanitize_user_text(item.event, EVENT_NAME_MAX_LENGTH) for item in response.results)
    return [name for name in sanitized if name]


def build_context_blob(team: Team, frequency: str) -> str:
    event_names = _top_event_names(team, EVENT_NAMES_SAMPLE_LIMIT)
    window_days = _window_days_for(frequency)
    now_iso = datetime.now(tz=UTC).isoformat(timespec="seconds")

    # Team / org names are also user-controlled and end up in the LLM context, so
    # apply the same sanitization as event names.
    team_name = sanitize_user_text(team.name, EVENT_NAME_MAX_LENGTH) or "(unnamed)"
    org_name = sanitize_user_text(team.organization.name, EVENT_NAME_MAX_LENGTH) or "(unnamed)"

    lines = [
        f"- Project: {team_name}",
        f"- Organization: {org_name}",
        f"- Project timezone: {team.timezone}",
        f"- Current UTC time: {now_iso}",
        f"- Suggested analysis window: last {window_days} day(s)",
    ]
    if event_names:
        lines.append("- Top events: " + ", ".join(event_names))
    else:
        lines.append("- Top events: (none recorded yet)")
    return "\n".join(lines)


def generate_query_plan(*, cleaned_prompt: str, context_blob: str, subscription: Subscription) -> QueryPlan:
    team = subscription.team
    user = subscription.created_by
    if user is None:
        raise PromptRejectedError("AI subscription must have a creator to run.")

    model_name = resolve_ai_model(subscription.ai_config, "planner_model", DEFAULT_PLANNER_MODEL)
    llm = MaxChatOpenAI(
        model=model_name,
        temperature=0,
        user=user,
        team=team,
        billable=False,
        posthog_properties={
            "feature": "ai_subscription",
            "stage": "plan",
            "subscription_id": subscription.id,
        },
    ).with_structured_output(QueryPlan, method="json_schema", include_raw=False)

    # Single-pass substitution: chained .replace() is order-dependent — if the first
    # substitution's value contained `{{{cleaned_prompt}}}` literally (e.g. an event
    # name in `context_blob`), the second .replace() would expand it again.
    substitutions = {"context_blob": context_blob, "cleaned_prompt": cleaned_prompt}
    rendered_prompt = re.sub(
        r"\{\{\{(\w+)\}\}\}",
        lambda m: substitutions.get(m.group(1), m.group(0)),
        PLAN_GENERATION_PROMPT,
    )

    result = llm.invoke([("system", rendered_prompt)])
    if not isinstance(result, QueryPlan):
        raise PromptRejectedError("Planner returned a malformed plan.")
    return result


def build_enriched_prompt(subscription: Subscription) -> EnrichedPromptSpec:
    cleaned = sanitize_prompt(subscription.prompt)
    context_blob = build_context_blob(subscription.team, subscription.frequency)
    plan = generate_query_plan(cleaned_prompt=cleaned, context_blob=context_blob, subscription=subscription)
    return EnrichedPromptSpec(cleaned_prompt=cleaned, context_blob=context_blob, plan=plan)
