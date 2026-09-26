"""
Match a filter picker search that found no events to the PostHog core events it may mean.

A person who does not know an event's name types what the event does, such as "browser capture" for
autocapture. Fuzzy search cannot bridge that gap, so each core event becomes one yes/no question to the
decision model, with the event's label and description as the meaning to judge.
"""

import hashlib
import contextvars
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from django.core.cache import cache

import structlog
from pydantic import TypeAdapter, ValidationError

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.llm.gateway_client import team_distinct_id
from posthog.llm.system_one import NoulAnswer, NoulQuestion, SystemOneRequestFailed, SystemOneResult
from posthog.llm.system_one_client import GATEWAY_MAX_QUESTIONS, SystemOneClient, build_system_one_client
from posthog.models import EventDefinition
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP

from .classify import (
    CACHE_TTL_SECONDS,
    MAX_QUERY_CHARS,
    MIN_QUERY_CHARS,
    SEARCH_INTENT_MODEL,
    SEARCH_INTENT_TIMEOUT_SECONDS,
    redact_values,
)
from .contracts import EventMatch, EventMatchRequest

logger = structlog.get_logger(__name__)

EVENT_MATCH_FEATURE_FLAG = "taxonomic-filter-event-match"
# The picker shows a suggestion only above this probability. Tune it from the eval suite, not by feel.
MATCH_THRESHOLD = 0.7
# The picker shows at most this many, after it removes the events it excludes, so the endpoint returns them all.
MAX_MATCHES = 3
CACHE_KEY_PREFIX = "taxonomic_search_intent:event_match:v1"

_CACHED_MATCHES = TypeAdapter(list[EventMatch])


@frozen
class CoreEventCandidate:
    label: str
    # The description the model judges the search against.
    meaning: str


def _candidates() -> dict[str, CoreEventCandidate]:
    """Every core event a picker can select, by event name."""
    candidates: dict[str, CoreEventCandidate] = {}
    for name, definition in CORE_FILTER_DEFINITIONS_BY_GROUP["events"].items():
        # "All events" is not an event. Events hidden from query builders stay in: the picker drops them from
        # the suggestions when it hides them, which depends on flags only the frontend knows.
        if name == "All events":
            continue
        meaning = definition.get("description_llm") or definition.get("description") or ""
        candidates[name] = CoreEventCandidate(label=definition["label"], meaning=meaning)
    return candidates


CORE_EVENT_CANDIDATES = _candidates()
_CANDIDATES_DIGEST = hashlib.sha256(repr(sorted(CORE_EVENT_CANDIDATES.items())).encode()).hexdigest()[:16]


def event_match_state(query: str) -> str:
    return "\n".join(
        [
            "A person searches the events list of the filter picker in PostHog, a product analytics tool.",
            "No event name matches the search, so the person may describe an event instead of naming it.",
            f"Search: {query}",
        ]
    )


def _question(candidate: CoreEventCandidate) -> NoulQuestion:
    return NoulQuestion(
        instructions=f"Does the search look for the {candidate.label} event? {candidate.meaning}".strip(),
        criteria_true="The search describes this event, uses a synonym for it, or names what it records.",
        criteria_false="The search is about something else.",
    )


def _ask(client: SystemOneClient, state: str, names: Sequence[str]) -> SystemOneResult:
    questions = {f"e{index}": _question(CORE_EVENT_CANDIDATES[name]) for index, name in enumerate(names)}
    return client.decide(state=state, questions=questions)


@frozen
class _ModelAnswers:
    probabilities: dict[str, float]
    # False when some requests failed, so the probabilities cover only part of the core events.
    complete: bool


def _ask_chunk(client: SystemOneClient, state: str, names: Sequence[str], team_id: int) -> SystemOneResult | None:
    """None when this request fails. The failure goes to error tracking and the logs, and the other chunks still count."""
    try:
        return _ask(client, state, names)
    except SystemOneRequestFailed as error:
        # Only the team and the failure go out: the error message never carries the search text.
        logger.warning(
            "taxonomic_event_match_chunk_failed",
            team_id=team_id,
            status_code=error.status_code,
            chunk_size=len(names),
        )
        capture_exception(error, {"team_id": team_id, "chunk_size": len(names)})
        return None


def _probabilities(team_id: int, query: str) -> _ModelAnswers:
    """The model's probability for every core event it answered. Raises the System One errors when no request succeeds."""
    names = list(CORE_EVENT_CANDIDATES)
    # The gateway takes a bounded number of questions per request, so the candidates go out in parallel chunks.
    chunks = [names[start : start + GATEWAY_MAX_QUESTIONS] for start in range(0, len(names), GATEWAY_MAX_QUESTIONS)]
    client = build_system_one_client(
        model=SEARCH_INTENT_MODEL,
        ai_product="taxonomic_filter",
        distinct_id=team_distinct_id(team_id),
        timeout=SEARCH_INTENT_TIMEOUT_SECONDS,
    )
    state = event_match_state(query)
    with ThreadPoolExecutor(max_workers=len(chunks), thread_name_prefix="event-match") as executor:
        # A fresh copy of the request context per chunk keeps its log and error-tracking tags on the failure reports.
        futures = [
            executor.submit(contextvars.copy_context().run, _ask_chunk, client, state, chunk, team_id)
            for chunk in chunks
        ]
        results = [future.result() for future in futures]
    if all(result is None for result in results):
        raise SystemOneRequestFailed("Every event match request failed")
    probabilities: dict[str, float] = {}
    for chunk, result in zip(chunks, results):
        if result is None:
            continue
        for index, name in enumerate(chunk):
            answer = result.answers[f"e{index}"]
            if isinstance(answer, NoulAnswer):
                probabilities[name] = answer.probability
    return _ModelAnswers(probabilities=probabilities, complete=None not in results)


def _cache_key(team_id: int, query: str) -> str:
    # Keyed per team, so a fast answer cannot tell one team what another team searched.
    digest = hashlib.sha256(f"{SEARCH_INTENT_MODEL}\n{MATCH_THRESHOLD}\n{query}".encode()).hexdigest()
    return f"{CACHE_KEY_PREFIX}:{_CANDIDATES_DIGEST}:{team_id}:{digest}"


def likely_core_events(
    team_id: int, query: str, *, use_cache: bool = True, require_complete: bool = False
) -> list[EventMatch]:
    """Every core event the model finds likely, strongest first, before the check against ingested events.

    The model reads the search with its values replaced by placeholders, and nothing when only values are left.
    With `require_complete`, a failed request raises instead of leaving its events out of the answer.
    """
    model_query = redact_values(query)
    if model_query is None:
        return []
    key = _cache_key(team_id, model_query)
    if use_cache:
        cached = cache.get(key)
        # The Django cache pickles what it stores, so matches go in as JSON text and come out schema-validated.
        if isinstance(cached, str):
            try:
                return _CACHED_MATCHES.validate_json(cached)
            except ValidationError:
                pass
    answers = _probabilities(team_id, model_query)
    if require_complete and not answers.complete:
        raise SystemOneRequestFailed("Some event match requests failed")
    likely = sorted(
        (
            EventMatch(name=name, label=CORE_EVENT_CANDIDATES[name].label, probability=probability)
            for name, probability in answers.probabilities.items()
            if probability >= MATCH_THRESHOLD
        ),
        key=lambda match: match.probability,
        reverse=True,
    )
    # A partial answer is not cached, so the next search asks again for the events that failed.
    if use_cache and answers.complete:
        cache.set(key, _CACHED_MATCHES.dump_json(likely).decode(), CACHE_TTL_SECONDS)
    return likely


def _ingested(project_id: int, names: Sequence[str]) -> set[str]:
    return set(
        # A definition can exist before its first event arrives, and only a seen event has data to show.
        EventDefinition.objects.filter(
            team__project_id=project_id, name__in=names, last_seen_at__isnull=False
        ).values_list("name", flat=True)
    )


def match_core_events(request: EventMatchRequest, *, use_cache: bool = True) -> list[EventMatch]:
    """The core events the search most likely means, strongest first, limited to events the project has ingested.

    Raises the System One errors; the caller decides whether a failed answer matters.
    """
    query = " ".join(request.query.split())
    if not MIN_QUERY_CHARS <= len(query) <= MAX_QUERY_CHARS:
        return []
    likely = likely_core_events(request.team_id, query, use_cache=use_cache)
    if not likely:
        return []
    # A suggestion for an event the project never sent would lead to an empty insight.
    ingested = _ingested(request.project_id, [match.name for match in likely])
    return [match for match in likely if match.name in ingested]
