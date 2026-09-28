"""
The question and the tab meanings the decision model reads for a filter picker search.

They live in PostHog's own prompt management, as `taxonomic-filter-search-intent` in the PostHog project,
so a new wording ships by moving the `production` label and not by a deploy. The prompt text is the
question. Its config holds the tab meanings as `options` and the `confident_threshold`. The bundled
copy below is the fallback when the managed prompt is unreachable or malformed; keep it close to the
`production` version so a fallback answer reads the same.
"""

import time
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import structlog
import posthoganalytics
from posthoganalytics.ai.prompts import PromptResult, Prompts

from posthog.dataclasses import frozen
from posthog.llm.system_one_client import GATEWAY_MAX_CHOICE_OPTIONS

logger = structlog.get_logger(__name__)

SEARCH_INTENT_PROMPT_NAME = "taxonomic-filter-search-intent"
SEARCH_INTENT_PROMPT_LABEL = "production"
PROMPT_REFRESH_SECONDS = 60


@frozen
class SearchIntentPrompt:
    instructions: str
    options: Mapping[str, str]
    confident_threshold: float
    # None for the bundled copy, so analysis can tell a fallback answer from a managed one.
    version: int | None


BUNDLED_SEARCH_INTENT_PROMPT = SearchIntentPrompt(
    instructions="Which tab of the filter picker holds the thing this person searches for?",
    options={
        "events": "An event: something a person did, such as a pageview, a signup, a purchase or a click.",
        "actions": "A saved action: a named combination of events.",
        "event_properties": (
            "A property of one event, such as the current URL, path, browser, device, UTM tags, referrer "
            "or the country the event came from."
        ),
        "person_properties": (
            "A property of a person, such as their email address, name, company, plan or the date they signed up."
        ),
        "session_properties": (
            "A property of a whole session, such as its duration, entry URL, exit URL or channel type."
        ),
        "cohorts": "A saved cohort: a named group of people.",
        "feature_flags": "A feature flag, or the people who match a feature flag.",
        "event_feature_flags": "The value of a feature flag that was active when an event happened.",
        "pageview_urls": "One specific page URL.",
        "email_addresses": "One specific person's email address.",
        "elements": "An element on the page, such as a button, a link or a form field.",
    },
    # The frontend acts on an answer only above this confidence. Tune it from the eval suite, not by feel.
    confident_threshold=0.6,
    version=None,
)


def _valid_options(value: Any) -> dict[str, str] | None:
    # The gateway refuses a choice question with more options than this before it sends anything.
    if not isinstance(value, dict) or not 1 <= len(value) <= GATEWAY_MAX_CHOICE_OPTIONS:
        return None
    if not all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in value.items()):
        return None
    return {k: v.strip() for k, v in value.items()}


def _valid_threshold(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 < value <= 1:
        return None
    return float(value)


def parse_search_intent_prompt(result: PromptResult) -> SearchIntentPrompt:
    """A malformed part falls back to the bundled part, so one bad config key never stops the picker."""
    if result.source == "code_fallback":
        return BUNDLED_SEARCH_INTENT_PROMPT
    config = result.config or {}
    options = _valid_options(config.get("options"))
    threshold = _valid_threshold(config.get("confident_threshold"))
    if options is None or threshold is None:
        logger.warning(
            "taxonomic_search_intent_prompt_config_invalid",
            version=result.version,
            options_valid=options is not None,
            threshold_valid=threshold is not None,
        )
    bundled = BUNDLED_SEARCH_INTENT_PROMPT
    return SearchIntentPrompt(
        instructions=result.prompt.strip() or bundled.instructions,
        options=options if options is not None else bundled.options,
        confident_threshold=threshold if threshold is not None else bundled.confident_threshold,
        version=result.version,
    )


def fetch_search_intent_prompt(*, label: str | None = None, version: int | None = None) -> SearchIntentPrompt:
    """Blocks on the network for up to the SDK timeout. Request code reads `current_search_intent_prompt` instead."""
    # Without a key (tests, local dev, self-hosted) the SDK still sends the request and gets a 401.
    if not posthoganalytics.personal_api_key:
        return BUNDLED_SEARCH_INTENT_PROMPT
    # Built per fetch because the key is set in apps.ready(), after this module can be imported.
    prompts = Prompts(posthoganalytics, capture_errors=True)
    result = prompts.get(
        SEARCH_INTENT_PROMPT_NAME,
        with_metadata=True,
        label=label if version is None else None,
        version=version,
        fallback=BUNDLED_SEARCH_INTENT_PROMPT.instructions,
    )
    return parse_search_intent_prompt(result)


class _PromptRefresher:
    # The SDK fetch blocks for up to 10 s on a cache miss and the picker's budget is 2 s, so a request
    # reads the last prompt it has and at most one background fetch replaces it.
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="search-intent-prompt")
        self._prompt = BUNDLED_SEARCH_INTENT_PROMPT
        self._refreshed_at = float("-inf")
        self._refreshing = False

    def current(self) -> SearchIntentPrompt:
        with self._lock:
            if not self._refreshing and time.monotonic() - self._refreshed_at >= PROMPT_REFRESH_SECONDS:
                self._refreshing = True
                self._executor.submit(self._refresh)
            return self._prompt

    def _refresh(self) -> None:
        try:
            prompt = fetch_search_intent_prompt(label=SEARCH_INTENT_PROMPT_LABEL)
        except Exception:
            logger.exception("taxonomic_search_intent_prompt_refresh_failed")
            prompt = None
        with self._lock:
            if prompt is not None and (prompt.version is not None or self._prompt.version is None):
                self._prompt = prompt
            self._refreshed_at = time.monotonic()
            self._refreshing = False


_REFRESHER = _PromptRefresher()


def current_search_intent_prompt() -> SearchIntentPrompt:
    """Never blocks. The first requests after boot read the bundled copy until the first fetch lands."""
    return _REFRESHER.current()
