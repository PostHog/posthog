"""
Classify a filter picker search: which tab (taxonomic group) does the person look for?

Value-shaped input (an email address, a URL, a path) is matched by pattern and never goes to the model.
Everything else is one multiple choice question to the decision model, over the tabs the picker shows.
"""

import re
import hashlib
import dataclasses

from django.conf import settings
from django.core.cache import cache

import structlog
import posthoganalytics
from pydantic import TypeAdapter, ValidationError

from posthog.llm.gateway_client import team_distinct_id
from posthog.llm.system_one import ChoiceAnswer, ChoiceQuestion
from posthog.llm.system_one_client import build_system_one_client

from .contracts import SearchIntent, SearchIntentRequest, SearchIntentSource
from .prompt import SearchIntentPrompt, current_search_intent_prompt

logger = structlog.get_logger(__name__)

SEARCH_INTENT_FEATURE_FLAG = "taxonomic-filter-search-intent"
SEARCH_INTENT_MODEL = "posthog/hogference/jevk5-fp8-0.2"
MIN_QUERY_CHARS = 2
MAX_QUERY_CHARS = 64
# The picker waits for no answer, so a late answer is worth nothing and a short timeout frees the worker.
SEARCH_INTENT_TIMEOUT_SECONDS = 2.0
CACHE_TTL_SECONDS = 24 * 60 * 60
# Keyed per team: a cache shared across teams lets a fast answer tell one team what another team searched.
CACHE_KEY_PREFIX = "taxonomic_search_intent:v1"

_EMAIL_VALUE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)
_URL_VALUE = re.compile(r"^(https?://|www\.)", re.IGNORECASE)
# Any leading slash, because a query string or a fragment can carry a token or personal data.
_PATH_VALUE = re.compile(r"^/")
# Long digit runs are ids or phone numbers, which are not ours to send.
_DIGIT_RUN = re.compile(r"\d{6,}")
# One word of 8+ characters that mixes letters with two or more digits is a token or an id, such as a session id.
_OPAQUE_TOKEN = re.compile(r"^(?=\S*[a-z])(?=\S*\d\S*\d)\S{8,}$", re.IGNORECASE)
_SCENE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_QUESTION_ID = "tab"
# The Django cache pickles what it stores, so the intent goes in as JSON text and comes out schema-validated.
_CACHED_INTENT = TypeAdapter(SearchIntent)


def search_intent_enabled(distinct_id: str, organization_id: str) -> bool:
    """The flag assigns the experiment arms. Every arm asks, so any value other than off enables the endpoint.

    Dark launch: only local development and the US cloud, so no flag change can bring it up in the EU or on
    self-hosted. DEBUG bypasses the flag because the analytics SDK is disabled in local development.
    """
    if not (settings.DEBUG or (settings.CLOUD_DEPLOYMENT or "").upper() == "US"):
        return False
    if settings.DEBUG:
        return True
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SEARCH_INTENT_FEATURE_FLAG,
                distinct_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("taxonomic_search_intent_flag_check_failed")
        return False


def _skipped() -> SearchIntent:
    return SearchIntent(group_type=None, confidence=0.0, is_confident=False, source=SearchIntentSource.SKIPPED)


def _rule_match(group_type: str) -> SearchIntent:
    return SearchIntent(group_type=group_type, confidence=1.0, is_confident=True, source=SearchIntentSource.RULE)


def rule_intent(query: str, available_group_types: tuple[str, ...]) -> SearchIntent | None:
    """Match value-shaped input. None means the query is not a value and the model can read it."""
    if "@" in query:
        if _EMAIL_VALUE.match(query) and "email_addresses" in available_group_types:
            return _rule_match("email_addresses")
        if _EMAIL_VALUE.match(query) and "person_properties" in available_group_types:
            return _rule_match("person_properties")
        # A partial email address is still personal data, so it never goes to the model.
        return _skipped()
    if _URL_VALUE.match(query) or _PATH_VALUE.match(query):
        if "pageview_urls" in available_group_types:
            return _rule_match("pageview_urls")
        return _skipped()
    if _DIGIT_RUN.search(query) or any(_OPAQUE_TOKEN.match(word) for word in query.split()):
        return _skipped()
    return None


def search_intent_state(query: str, active_group_type: str, scene: str | None) -> str:
    lines = ["A person uses the filter picker in PostHog, a product analytics tool."]
    if scene and _SCENE.match(scene):
        lines.append(f"Page: {scene}")
    lines.append(f"Open tab: {active_group_type}")
    lines.append(f"Search: {query}")
    return "\n".join(lines)


def _cache_key(
    team_id: int, model: str, state: str, instructions: str, options: dict[str, str], threshold: float
) -> str:
    # The prompt text is in the key, not its version, so a new managed version and the bundled copy never share answers.
    parts = [model, state, instructions, str(threshold), *(f"{k}={v}" for k, v in sorted(options.items()))]
    digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()
    return f"{CACHE_KEY_PREFIX}:{team_id}:{digest}"


# The cross-category tab already shows every group, so there is no better tab to suggest from it.
_ALL_GROUPS_TAB = "suggested_filters"


def with_switch_suggestion(intent: SearchIntent, active_group_type: str) -> SearchIntent:
    """Suggest a different tab only for a confident answer that names a tab other than the open one."""
    suggests_switch = (
        intent.is_confident
        and intent.group_type is not None
        and intent.group_type != active_group_type
        and active_group_type != _ALL_GROUPS_TAB
    )
    return dataclasses.replace(intent, suggests_switch=suggests_switch)


def classify_search_intent(
    request: SearchIntentRequest, *, use_cache: bool = True, prompt: SearchIntentPrompt | None = None
) -> SearchIntent:
    """Raises the System One errors; the caller decides whether a failed answer matters."""
    prompt = prompt or current_search_intent_prompt()
    return with_switch_suggestion(_classify(request, prompt, use_cache=use_cache), request.active_group_type)


def _classify(request: SearchIntentRequest, prompt: SearchIntentPrompt, *, use_cache: bool) -> SearchIntent:
    query = " ".join(request.query.split())
    if not MIN_QUERY_CHARS <= len(query) <= MAX_QUERY_CHARS:
        return _skipped()
    matched = rule_intent(query, request.available_group_types)
    if matched is not None:
        return matched

    options = {
        group_type: meaning
        for group_type, meaning in prompt.options.items()
        if group_type in request.available_group_types
    }
    if len(options) < 2:
        return _skipped()

    state = search_intent_state(query, request.active_group_type, request.scene)
    key = _cache_key(
        request.team_id, SEARCH_INTENT_MODEL, state, prompt.instructions, options, prompt.confident_threshold
    )
    if use_cache:
        cached = _cached_intent(key)
        if cached is not None:
            return cached

    # No TypeSafe fallback: a search is customer text, and TypeSafe is a third party.
    client = build_system_one_client(
        model=SEARCH_INTENT_MODEL,
        ai_product="taxonomic_filter",
        distinct_id=team_distinct_id(request.team_id),
        timeout=SEARCH_INTENT_TIMEOUT_SECONDS,
    )
    result = client.decide(
        state=state, questions={_QUESTION_ID: ChoiceQuestion(instructions=prompt.instructions, criteria=options)}
    )
    answer = result.answers[_QUESTION_ID]
    if not isinstance(answer, ChoiceAnswer) or answer.choice not in options:
        logger.warning("taxonomic_search_intent_unexpected_answer", team_id=request.team_id)
        return _skipped()
    intent = SearchIntent(
        group_type=answer.choice,
        confidence=answer.confidence,
        is_confident=answer.confidence >= prompt.confident_threshold,
        source=SearchIntentSource.MODEL,
        prompt_version=prompt.version,
    )
    if use_cache:
        cache.set(key, _CACHED_INTENT.dump_json(intent).decode(), CACHE_TTL_SECONDS)
    return intent


def _cached_intent(key: str) -> SearchIntent | None:
    cached = cache.get(key)
    if not isinstance(cached, str):
        return None
    try:
        return _CACHED_INTENT.validate_json(cached)
    except ValidationError:
        return None
