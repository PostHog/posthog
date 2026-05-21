import re
from datetime import UTC, datetime, timedelta
from typing import Optional, Union

from django.db.models import F, Q

import structlog

from posthog.schema import CachedTeamTaxonomyQueryResponse, TeamTaxonomyQuery

from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import EventDefinition, PropertyDefinition, Team, User
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.models.subscription import Subscription
from posthog.text_sanitization import sanitize_core_memory_text, sanitize_user_text

from ee.hogai.llm import MaxChatOpenAI
from ee.tasks.subscriptions.ai_subscription.prompts import PLAN_GENERATION_PROMPT
from ee.tasks.subscriptions.ai_subscription.schemas import EnrichedPromptSpec, QueryPlan

logger = structlog.get_logger(__name__)


PROMPT_MAX_LENGTH = 4000
EVENT_NAMES_SAMPLE_LIMIT = 20
# Cap on the "events defined but receiving no data" list injected into context. Bounds both the
# Postgres scan and the context size — a noisy taxonomy can have hundreds of dormant definitions.
NO_DATA_EVENT_NAMES_LIMIT = 25
PERSON_PROPERTY_NAMES_LIMIT = 30
EVENT_NAME_MAX_LENGTH = 120

DEFAULT_PLANNER_MODEL = "gpt-4.1-mini"
DEFAULT_SYNTHESIS_MODEL = "gpt-4.1-mini"
# Wall-clock bound on the planner LLM call; combined with the activity timeout and
# `max_retries` on `MaxChatOpenAI` (3), prevents a single stuck request from soaking
# the delivery budget.
_PLANNER_LLM_TIMEOUT_SECONDS = 90.0
# Whitelist of models a user can opt their subscription into via `ai_config`.
# Without this, any authenticated user could PATCH `ai_config: {"model": ...}` and
# force scheduled deliveries to use an arbitrarily expensive model.
ALLOWED_AI_MODELS = frozenset({"gpt-4.1-mini", "gpt-4.1-nano", "gpt-4.1"})


def resolve_ai_model(ai_config: dict | None, key: str, default: str) -> str:
    requested = (ai_config or {}).get(key)
    if isinstance(requested, str) and requested in ALLOWED_AI_MODELS:
        return requested
    return default


# No second-layer regex blocklist: the prompt is summarized back to the same user who
# wrote it, so injection here is self-targeted. The structural defenses are the
# `<user_prompt>` framing in the system prompt and `sanitize_core_memory_text` stripping
# `<system>`-style markers; layering ad-hoc patterns on top just creates false positives
# for legitimate phrasings like "ignore null values".

_FREQUENCY_WINDOW_DAYS = {
    Subscription.SubscriptionFrequency.DAILY: 1,
    Subscription.SubscriptionFrequency.WEEKLY: 7,
    Subscription.SubscriptionFrequency.MONTHLY: 30,
    Subscription.SubscriptionFrequency.YEARLY: 365,
}

DEFAULT_AD_HOC_WINDOW_DAYS = 7


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

    return cleaned


def frequency_to_window_days(frequency: str) -> int:
    """Map a subscription frequency to the analysis window the LLM should consider."""
    return _FREQUENCY_WINDOW_DAYS.get(frequency, DEFAULT_AD_HOC_WINDOW_DAYS)


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


def _no_data_event_names(team: Team, window_days: int, limit: int) -> list[str]:
    # Ground truth for "events with no data" lives in the event-definitions taxonomy, not the events
    # table (which only contains events that fired). An event whose `last_seen_at` predates the window —
    # or was never seen — had no data in it. `last_seen_at` is maintained on ingestion so it can lag
    # slightly, but it's the authoritative taxonomy signal and stops the LLM fabricating a plausible
    # list of dormant events from its general knowledge of PostHog event names.
    cutoff = datetime.now(tz=UTC) - timedelta(days=window_days)
    names = (
        EventDefinition.objects.filter(team_id=team.pk)
        .filter(Q(last_seen_at__isnull=True) | Q(last_seen_at__lt=cutoff))
        .order_by(F("last_seen_at").desc(nulls_last=True), "name")
        .values_list("name", flat=True)[:limit]
    )
    sanitized = (sanitize_user_text(name, EVENT_NAME_MAX_LENGTH) for name in names)
    return [name for name in sanitized if name]


def _person_property_names(team: Team, limit: int) -> list[str]:
    names = (
        PropertyDefinition.objects.filter(team_id=team.pk, type=PropertyDefinition.Type.PERSON)
        .order_by("name")
        .values_list("name", flat=True)[:limit]
    )
    sanitized = (sanitize_user_text(name, EVENT_NAME_MAX_LENGTH) for name in names)
    return [name for name in sanitized if name]


def _group_type_labels(team: Team) -> list[str]:
    # Map each configured group type to its HogQL virtual-join path (group_0..group_4) so the planner
    # knows what `group_<index>` means for this project (e.g. group_0 = organization). These are joined
    # by the engine automatically when referenced — the planner never writes a JOIN.
    labels: list[str] = []
    for gt in get_group_types_for_project(team.project_id or team.pk):
        name = sanitize_user_text(gt.get("group_type", ""), EVENT_NAME_MAX_LENGTH)
        index = gt.get("group_type_index")
        if name and index is not None:
            labels.append(f"group_{index} = {name}")
    return labels


def build_context_blob(team: Team, window_days: int) -> str:
    event_names = _top_event_names(team, EVENT_NAMES_SAMPLE_LIMIT)
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

    no_data_events = _no_data_event_names(team, window_days, NO_DATA_EVENT_NAMES_LIMIT)
    if no_data_events:
        lines.append(
            f"- Events defined but with no data in the last {window_days} day(s): " + ", ".join(no_data_events)
        )

    person_properties = _person_property_names(team, PERSON_PROPERTY_NAMES_LIMIT)
    if person_properties:
        lines.append(
            "- Person properties (reference as person.properties.<name>, no JOIN needed): "
            + ", ".join(person_properties)
        )

    group_labels = _group_type_labels(team)
    if group_labels:
        lines.append(
            "- Group/account types (reference as group_<index>.properties.<name>, no JOIN needed): "
            + ", ".join(group_labels)
        )
    return "\n".join(lines)


def generate_query_plan(
    *,
    cleaned_prompt: str,
    context_blob: str,
    team: Team,
    user: User,
    ai_config: Optional[dict] = None,
    trace_correlation_id: Optional[Union[int, str]] = None,
) -> QueryPlan:
    # `user is None` is enforced at the public entry point (`generate_ai_report`)
    # which is the only caller path into here. Don't repeat the check.
    model_name = resolve_ai_model(ai_config, "planner_model", DEFAULT_PLANNER_MODEL)
    posthog_properties: dict[str, Union[str, int]] = {"feature": "ai_subscription", "stage": "plan"}
    if trace_correlation_id is not None:
        posthog_properties["subscription_id"] = trace_correlation_id
    llm = MaxChatOpenAI(
        model=model_name,
        temperature=0,
        timeout=_PLANNER_LLM_TIMEOUT_SECONDS,
        user=user,
        team=team,
        # Planner LLM spend is billable — AI subscription usage counts against the
        # team's AI credits.
        billable=True,
        posthog_properties=posthog_properties,
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


def build_enriched_prompt(
    *,
    team: Team,
    user: User,
    prompt: Optional[str],
    window_days: int,
    ai_config: Optional[dict] = None,
    trace_correlation_id: Optional[Union[int, str]] = None,
) -> EnrichedPromptSpec:
    cleaned = sanitize_prompt(prompt)
    context_blob = build_context_blob(team, window_days)
    plan = generate_query_plan(
        cleaned_prompt=cleaned,
        context_blob=context_blob,
        team=team,
        user=user,
        ai_config=ai_config,
        trace_correlation_id=trace_correlation_id,
    )
    return EnrichedPromptSpec(cleaned_prompt=cleaned, context_blob=context_blob, plan=plan)
