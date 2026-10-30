from __future__ import annotations

import json
import math
import hashlib
from typing import TYPE_CHECKING, Any

from django.core.cache import cache

import structlog
from openai import APIError

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.llm.gateway_client import GatewayNotConfiguredError, build_openai_client, team_distinct_id

from products.product_analytics.backend.facade.api import get_or_create_saved_insight, saved_insights_for_read

from ..facade.contracts import GuardrailOption, MeasureOption, MeasureSearch
from .metrics import metric, proposed_plan, refresh_metrics
from .workspace import get_settings, project_id

if TYPE_CHECKING:
    from posthog.models import Team, User

logger = structlog.get_logger(__name__)

MODEL = "gpt-6-luna"
MAX_INSIGHTS = 80
MAX_EVENTS = 80
MAX_OPTIONS = 3
SPARK_POINTS = 30
MAX_DRAFT = 200
DRAFT_STARTS = ("Number of", "Share of", "Average")
ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
FLOOR_EVENTS = 200
CACHE_SECONDS = 600
PERIODS = {"hour": "per hour", "day": "per day", "week": "per week", "month": "per month"}
UNCHARTED = {"ActionsTable", "ActionsPie", "BoldNumber", "WorldMap", "ActionsBarValue"}

PROMPT = """You help a product owner pick the number that a bet will move.
The owner wrote what should change. Pick up to 3 measures that show it, best first.
Prefer a saved insight when it measures the same thing. When no saved insight fits, build a new measure from the events whenever the events show the action the owner wrote.
A count stays a count. A share or rate stays a share or rate.
A new measure uses only events from the list. It is one of:
- "users": the number of people who do the event, per day.
- "rate": people who do the numerator event divided by people who do the denominator event, per day.
- "per_person": the number of events divided by the number of people who do it, per day.
Always write "draft": one sentence that defines the measure this goal needs, for an analyst who will build it, even when no event shows it yet, because the analyst can add tracking. Say who is counted, which action, and in what time window, for example "Share of new uploaders who share a file within 24 hours of their first upload". Start with "Number of", "Share of" or "Average". Use at most 200 characters. Never write about missing data, and never repeat the belief.
Answer with JSON only:
{"draft": "<one sentence>", "options": [{"insight": "<short id>", "why": "<one short sentence>"},
             {"new": {"name": "<short name in sentence case, for example Share rate after upload>", "kind": "users|rate|per_person", "event": "<event>", "denominator": "<event or null>"}, "why": "<one short sentence>"}]}
Suggest only measures that count the same people and the same action the owner wrote. Return {"options": []} only when no saved insight and no event shows that action."""

GUARD = """You help a product owner protect their product while a bet tests changes.
The owner wrote the goal and chose the measure to move. Pick up to 3 guardrails: measures that a change for this goal could hurt, such as errors, core usage, or a nearby step that people might skip.
Never pick the chosen measure or a measure of the same action.
Prefer a saved insight. A new measure uses only events from the list, with the same shapes: "users", "rate" or "per_person".
Say which way is better for each guardrail.
Answer with JSON only:
{"options": [{"insight": "<short id>", "better": "higher|lower"},
             {"new": {"name": "<short name in sentence case>", "kind": "users|rate|per_person", "event": "<event>", "denominator": "<event or null>"}, "better": "higher|lower"}]}"""

CHECK = """You check measures that were suggested for a goal.
"fits": the measure counts the action the goal names, done by the people or things the goal names. A count, a share or a rate of that action fits. A measure for new people or first-time actions fits a goal about people in general.
"no": the measure counts another action or another thing. Uploads are not shares. Files are not dubs. People are not teams.
Answer with JSON only: {"checks": [{"id": "<id>", "verdict": "fits|no"}]}"""


def describe(query: dict[str, Any]) -> str | None:
    source = query.get("source", query) if query.get("kind") == "InsightVizNode" else query
    if source.get("kind") != "TrendsQuery":
        return None
    if (source.get("trendsFilter") or {}).get("display") in UNCHARTED:
        return None
    series = source.get("series") or []
    formula = (source.get("trendsFilter") or {}).get("formula")
    if len(series) != 1 and not formula:
        return None
    parts = [phrase(item) for item in series]
    period = PERIODS.get(source.get("interval") or "day", "per day")
    if formula and len(parts) == 2 and formula.replace(" ", "").upper() == "A/B":
        return f"{parts[0]} divided by {parts[1]}, {period}"
    if formula:
        return (
            f"{formula} of "
            + ", ".join(f"{chr(65 + index)} = {part}" for index, part in enumerate(parts))
            + f", {period}"
        )
    return f"{parts[0]}, {period}"


def phrase(item: dict[str, Any]) -> str:
    event = item.get("event") or item.get("name") or "an action"
    math = item.get("math") or "total"
    if math == "dau":
        return f"people who did {event}"
    if math == "first_time_for_user":
        return f"people who did {event} for the first time"
    if math in ("sum", "avg", "min", "max", "median") and item.get("math_property"):
        return f"{math} of {item['math_property']} on {event}"
    if math in ("unique_group", "weekly_active", "monthly_active", "unique_session"):
        return f"{math.replace('_', ' ')} of {event}"
    return f"times {event} happened"


def series_events(query: dict[str, Any]) -> list[str]:
    source = query.get("source", query) if query.get("kind") == "InsightVizNode" else query
    return [item["event"] for item in source.get("series") or [] if item.get("event")]


def new_query(kind: str, event: str, denominator: str | None) -> dict[str, Any] | None:
    numerator = {"kind": "EventsNode", "event": event, "math": "dau"}
    if kind == "users":
        return {"kind": "TrendsQuery", "series": [numerator], "interval": "day"}
    if kind == "rate" and denominator:
        return {
            "kind": "TrendsQuery",
            "series": [numerator, {"kind": "EventsNode", "event": denominator, "math": "dau"}],
            "interval": "day",
            "trendsFilter": {"formula": "A/B", "aggregationAxisFormat": "percentage_scaled"},
        }
    if kind == "per_person":
        return {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": event, "math": "total"}, numerator],
            "interval": "day",
            "trendsFilter": {"formula": "A/B"},
        }
    return None


def top_events(team: Team) -> list[str]:
    with tags_context(product=Product.BETS, feature=Feature.QUERY, team_id=team.id):
        rows = execute_hogql_query(
            "select event, count() as total from events where timestamp > now() - interval 30 day "
            "group by event order by total desc limit {limit}",
            team=team,
            placeholders={"limit": ast.Constant(value=MAX_EVENTS)},
            workload=Workload.ONLINE,
        ).results
    return [row[0] for row in rows]


def wait_days(team: Team, events: list[str]) -> dict[str, int]:
    if not events:
        return {}
    with tags_context(product=Product.BETS, feature=Feature.QUERY, team_id=team.id):
        rows = execute_hogql_query(
            """
            select e.event, count() as total,
                quantile(0.01)(dateDiff('second', f.first_seen, e.timestamp)) / 86400 as floor_days
            from events e
            join (select person_id, min(timestamp) as first_seen from events
                  where timestamp > now() - interval 60 day group by person_id) f on e.person_id = f.person_id
            where e.timestamp > now() - interval 30 day and e.event in {events}
            group by e.event""",
            team=team,
            placeholders={"events": ast.Constant(value=tuple(events))},
            workload=Workload.ONLINE,
        ).results
    return {row[0]: math.floor(row[2]) for row in rows if row[1] >= FLOOR_EVENTS and row[2] >= 1}


class MeasureModelUnavailable(Exception):
    pass


def complete(team: Team, system: str, content: str) -> dict:
    try:
        client = build_openai_client("bets", ai_product="bets", distinct_id=team_distinct_id(team.id))
        response = client.chat.completions.create(
            model=MODEL,
            response_format={"type": "json_object"},
            user=team_distinct_id(team.id),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
        )
    except (APIError, GatewayNotConfiguredError) as error:
        logger.warning("bets_measure_model_failed", team_id=team.id, error=str(error))
        raise MeasureModelUnavailable from error
    try:
        answer = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        return {}
    return answer if isinstance(answer, dict) else {}


def ask(team: Team, system: str, goal: str, catalog: Catalog, extra: str = "") -> dict:
    listing = "\n".join(f"- {short_id}: {name} ({summary})" for short_id, (name, summary) in catalog.insights.items())
    return complete(
        team,
        system,
        f"What should change: {goal}{extra}\n\nSaved insights:\n{listing or '- none'}\n\nEvents:\n{', '.join(catalog.events)}",
    )


def check(team: Team, goal: str, candidates: dict[str, str]) -> dict[str, str]:
    listing = "\n".join(f"- {key}: {text}" for key, text in candidates.items())
    rows = complete(team, CHECK, f"What should change: {goal}\n\nMeasures:\n{listing}").get("checks") or []
    return {str(row.get("id")): row.get("verdict") for row in rows if isinstance(row, dict)}


@frozen
class Catalog:
    insights: dict[str, tuple[str, str]]
    queries: dict[str, dict]
    events: list[str]


def catalog(team: Team, user: User) -> Catalog:
    saved = saved_insights_for_read(team=team, user=user, limit=MAX_INSIGHTS)
    return Catalog(
        insights={
            item.short_id: (item.name or "Untitled", summary)
            for item in saved
            if (summary := describe(item.query)) is not None
        },
        queries={item.short_id: item.query for item in saved},
        events=top_events(team),
    )


def parse(raw: list, found: Catalog) -> list[tuple[str, str, dict, str, dict]]:
    taken = {name.lower() for name, _ in found.insights.values()}
    picks = []
    for item in raw[: MAX_OPTIONS + 2]:
        if not isinstance(item, dict):
            continue
        if item.get("insight") in found.insights:
            name, summary = found.insights[item["insight"]]
            picks.append((item["insight"], "existing", found.queries[item["insight"]], f"{name} ({summary})", item))
            continue
        spec = item.get("new") or {}
        event, denominator = spec.get("event"), spec.get("denominator")
        if event not in found.events or (denominator and denominator not in found.events):
            continue
        query = new_query(str(spec.get("kind")), event, denominator)
        if query is not None:
            name = str(spec.get("name") or "").strip()[:100]
            if not name or name.lower() in taken:
                definition = describe(query) or event
                name = (definition[:1].upper() + definition[1:])[:100]
            picks.append((f"new{len(picks)}", "new", {**query, "name": name}, f"{name} ({describe(query)})", item))
    return list({pick[3]: pick for pick in picks}.values())


def clean_draft(raw: object) -> str:
    draft = str(raw or "").strip()
    return draft if len(draft) <= MAX_DRAFT and draft.startswith(DRAFT_STARTS) else ""


def materialize(team: Team, user: User, goal: str, query: dict) -> tuple[str, str, dict]:
    body = {key: value for key, value in query.items() if key != "name"}
    digest = hashlib.sha256(f"{team.id}:{json.dumps(body, sort_keys=True)}".encode()).digest()
    short_id = "bm" + "".join(ALPHABET[byte % len(ALPHABET)] for byte in digest[:6])
    get_or_create_saved_insight(
        team_id=team.id,
        user_id=user.id,
        short_id=short_id,
        name=query["name"],
        description=goal[:400],
        query=body,
        saved=False,
    )
    return short_id, query["name"], body


def measure_options(team: Team, user: User, goal: str) -> MeasureSearch:
    key = f"bets:measure-search-2:{team.id}:{user.id}:{hashlib.sha256(goal.strip().lower().encode()).hexdigest()}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    found = catalog(team, user)
    try:
        answer = ask(team, PROMPT, goal, found)
    except MeasureModelUnavailable:
        return MeasureSearch(options=[], draft="")
    draft = clean_draft(answer.get("draft"))
    picks = [
        (key, source, str(item.get("why") or "")[:200], query, text)
        for key, source, query, text, item in parse(answer.get("options") or [], found)
    ]
    try:
        verdicts = check(team, goal, {key: text for key, _, _, _, text in picks}) if picks else {}
    except MeasureModelUnavailable:
        return MeasureSearch(options=[], draft=draft)
    kept = []
    for key, source, why, query, _ in picks:
        if verdicts.get(key) != "fits":
            continue
        if source == "new":
            key, _, query = materialize(team, user, goal, query)
        kept.append((key, source, why, query))
    picks = kept[: MAX_OPTIONS + 1]
    refresh_metrics(team, user, [pick[0] for pick in picks])
    waits = wait_days(team, sorted({event for pick in picks for event in series_events(pick[3])}))
    settings = get_settings(project_id(team))
    options = []
    for short_id, source, why, query in picks:
        measured = metric(team, user, short_id, complete=True)
        proposal = proposed_plan(
            team,
            user,
            short_id,
            audience=None,
            mde=settings.mde_percent,
            floor_days=math.ceil(settings.min_run_hours / 24),
        )
        planned = proposal[0] if proposal else None
        options.append(
            MeasureOption(
                insight=short_id,
                name=measured.name,
                source=source,
                why=why,
                definition=describe(query) or "",
                current=measured.current,
                unit=measured.unit,
                wait_days=max((waits.get(event, 0) for event in series_events(query)), default=0),
                test_days=planned.days if planned else None,
                values=measured.values[-SPARK_POINTS:],
                dates=measured.dates[-SPARK_POINTS:],
            )
        )
    options.sort(key=lambda option: (option.wait_days, option.test_days or 999))
    search = MeasureSearch(options=options[:MAX_OPTIONS], draft=draft)
    cache.set(key, search, CACHE_SECONDS)
    return search


def guardrail_options(team: Team, user: User, goal: str, measure: str) -> list[GuardrailOption]:
    key = f"bets:guardrails-1:{team.id}:{user.id}:{measure}:{hashlib.sha256(goal.strip().lower().encode()).hexdigest()}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    found = catalog(team, user)
    chosen = found.insights.get(measure)
    extra = f"\nChosen measure: {chosen[0]} ({chosen[1]})" if chosen else ""
    try:
        answer = ask(team, GUARD, goal, found, extra)
    except MeasureModelUnavailable:
        return []
    options = []
    for key_, source, query, _, item in parse(answer.get("options") or [], found):
        if key_ == measure:
            continue
        name = query.get("name") or found.insights.get(key_, ("",))[0]
        if source == "new":
            key_, name, query = materialize(team, user, goal, query)
        options.append(
            GuardrailOption(
                insight=key_,
                name=name,
                definition=describe(query) or "",
                direction="decrease" if item.get("better") == "lower" else "increase",
            )
        )
    options = options[:MAX_OPTIONS]
    cache.set(key, options, CACHE_SECONDS)
    return options
