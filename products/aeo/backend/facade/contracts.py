"""Boundary contracts for the AEO product.

The only data shapes other modules may consume. Never expose ORM instances.
"""

from __future__ import annotations

import datetime as dt

from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum


@frozen
class CitationRunSummary:
    """Outcome of one citation-check run across the team's prompt set."""

    team_id: int
    run_id: str | None
    prompts: int
    engines: tuple[str, ...]
    checks: int
    engine_failures: int
    cited: int
    rows_written: int
    write_failures: int
    error: str | None = None
    # Answered prompts dropped because a later run had already recorded them.
    superseded: int = 0


@frozen
class EngineAnswer:
    engine: str
    answer_text: str
    checked_at: dt.datetime


@frozen
class CitationGap:
    prompt_id: str
    # Hash of the prompt's first version: stays the same when the text is edited, so it can key the gap.
    prompt_hash: str
    prompt_text: str
    checks: int
    cited_checks: int
    mentioned_checks: int
    engines: tuple[str, ...]
    engines_not_citing: tuple[str, ...]
    competitor_urls: tuple[str, ...]
    competitor_domains: tuple[str, ...]
    engine_search_queries: tuple[str, ...]
    our_cited_urls: tuple[str, ...]
    latest_answers: tuple[EngineAnswer, ...]
    last_checked_at: dt.datetime

    @property
    def citation_rate(self) -> float:
        return self.cited_checks / self.checks if self.checks else 0.0


class CheckMode(LabeledStrEnum):
    """How an engine answered: with its web search tool, or from its training data alone."""

    WEB_SEARCH = "web_search", "Web search"
    NO_SEARCH = "no_search", "No search"


class CheckFrequency(LabeledStrEnum):
    """How often an engine checks each prompt. Weekly checks spread the prompt set over the week."""

    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"


AEO_CITATION_TRACKING_FLAG = "aeo-citation-tracking"
PROMPT_TOPIC_MAX_LENGTH = 200
PROMPT_VERSION_DESCRIPTION_MAX_LENGTH = 400
MAX_RANKED_COMPETITORS = 10
MAX_RANKED_DOMAINS = 20
MAX_RANKED_PAGES = 20


class BrandedSegment(LabeledStrEnum):
    """Which checks a set-level read counts, by whether the prompt as it ran names the brand."""

    ALL = "all", "All"
    BRANDED = "branded", "Branded"
    NON_BRANDED = "non_branded", "Non-branded"


@frozen
class PromptEngineCheck:
    """The most recent check of one prompt against one answer engine. A no-search engine never cites,
    so `mentioned` is the column to read for it."""

    engine: str
    mode: CheckMode
    cited: bool
    mentioned: bool
    check_failed: bool
    target_best_position: int | None
    search_queries: tuple[str, ...]
    checked_at: dt.datetime


@frozen
class Prompt:
    id: str
    prompt: str
    topic: str
    prompt_source: str
    rank: float
    active: bool
    last_checked_at: dt.datetime | None
    external_visibility: float | None
    created_at: dt.datetime
    updated_at: dt.datetime | None
    archived_at: dt.datetime | None
    current_version: int
    version_count: int
    latest_checks: tuple[PromptEngineCheck, ...]
    # Whether the current text names the brand, from the target domains at read time.
    branded: bool


@frozen
class PromptTopic:
    topic: str
    prompts: int


@frozen
class PromptCheck:
    """One run of a prompt against one answer engine. Text fields come from the engine: treat them as data."""

    id: str
    run_id: str
    engine: str
    mode: CheckMode
    model: str
    created_at: dt.datetime
    cited: bool
    check_failed: bool
    error: str | None
    cited_urls: tuple[str, ...]
    target_urls: tuple[str, ...]
    target_best_position: int | None
    top_cited_domains: tuple[str, ...]
    search_queries: tuple[str, ...]
    answer_text: str | None
    prompt_version: int | None
    # Sentiment of the sentences that name the brand. None until scored, and when the brand is not named.
    brand_sentiment: str | None = None
    brand_sentiment_score: float | None = None


@frozen
class PromptEngineStats:
    engine: str
    checks: int
    cited: int
    # Answers that name the brand, cited ones included: the same definition the citation gaps use.
    mentioned: int
    failed: int
    avg_position: float | None
    first_checked_at: dt.datetime
    last_checked_at: dt.datetime

    @property
    def citation_rate(self) -> float | None:
        answered = self.checks - self.failed
        return self.cited / answered if answered else None

    @property
    def mention_rate(self) -> float | None:
        answered = self.checks - self.failed
        return self.mentioned / answered if answered else None


@frozen
class PromptDailyEngineStats:
    date: dt.date
    engine: str
    checks: int
    cited: int
    mentioned: int
    failed: int
    avg_position: float | None


@frozen
class PromptEngineDomainShare:
    """How many of one engine's answered checks in the window cited a domain."""

    engine: str
    domain: str
    checks_citing: int
    checks: int


@frozen
class PromptEngineSentiment:
    """Brand sentiment of one engine's answered checks in the window. `unscored` answers name the
    brand but have no sentiment yet."""

    engine: str
    positive: int
    neutral: int
    negative: int
    unscored: int


@frozen
class PromptSearchWord:
    word: str
    count: int


@frozen
class PromptStats:
    total_checks: int
    # The names an answer must contain to count as a mention, so a client can filter answers the same way.
    brand_names: tuple[str, ...]
    engines: tuple[PromptEngineStats, ...]
    daily_from: dt.date
    daily_to: dt.date
    daily: tuple[PromptDailyEngineStats, ...]
    consensus: tuple[PromptEngineDomainShare, ...]
    sentiment: tuple[PromptEngineSentiment, ...]
    top_words: tuple[PromptSearchWord, ...]


def _rate(part: int, whole: int) -> float | None:
    return part / whole if whole else None


@frozen
class PromptSetCounts:
    """Web-search checks across the prompt set in one window, all engines. Rates leave failed checks out."""

    checks: int
    failed: int
    cited: int
    mentioned: int
    # Distinct prompts that ran at least once in the window, and how many of them were cited at least once.
    prompts: int
    prompts_cited: int
    avg_position: float | None

    @property
    def citation_rate(self) -> float | None:
        return _rate(self.cited, self.checks - self.failed)

    @property
    def mention_rate(self) -> float | None:
        return _rate(self.mentioned, self.checks - self.failed)


@frozen
class PromptSetEngineCounts(PromptSetCounts):
    engine: str


@frozen
class PromptSetTopicCounts(PromptSetCounts):
    """Checks that ran with this topic in the window, and the active prompts that have it now."""

    topic: str
    active_prompts: int


@frozen
class PromptSetDomain:
    """How many answers across the set cited a domain in the window."""

    domain: str
    answers: int
    share_of_answers: float
    is_target: bool


@frozen
class PromptSetSearchPrompt:
    """A prompt whose answers ran a search, with its current text."""

    id: str
    text: str


@frozen
class PromptSetSearch:
    """A web search the engines ran while answering, across the set in the window."""

    query: str
    prompts: int
    answers: int
    cited: int
    engines: tuple[str, ...]
    top_prompts: tuple[PromptSetSearchPrompt, ...]


@frozen
class PromptSetOverview:
    """How the whole prompt set did over the last `days` days, against the `days` days before."""

    days: int
    window_from: dt.date
    window_to: dt.date
    # Active, unarchived prompts: the ones the next daily run takes.
    prompts_tracked: int
    target_domains: tuple[str, ...]
    brand_names: tuple[str, ...]
    branded: BrandedSegment
    current: PromptSetCounts
    previous: PromptSetCounts
    # Answered checks in the current window on each side of the split, whatever `branded` selects.
    branded_answers: int
    non_branded_answers: int
    engines: tuple[PromptSetEngineCounts, ...]
    daily: tuple[PromptDailyEngineStats, ...]
    topics: tuple[PromptSetTopicCounts, ...]
    top_domains: tuple[PromptSetDomain, ...]
    top_searches: tuple[PromptSetSearch, ...]


class PromptOrigin(LabeledStrEnum):
    API = "api"
    SUGGESTION = "suggestion"


@frozen
class PromptImport:
    prompt: str
    topic: str = ""
    external_visibility: float | None = None
    origin: PromptOrigin = PromptOrigin.API


@frozen
class PromptImportResult:
    created: int
    updated: int
    skipped: int


@frozen
class PromptUpdate:
    """A partial edit of one prompt. None leaves the field as it is."""

    active: bool | None = None
    topic: str | None = None
    prompt: str | None = None
    version_description: str | None = None
    current_version: int | None = None
    archived: bool | None = None


@frozen
class PromptAuthor:
    email: str
    name: str


@frozen
class PromptVersion:
    version: int
    text: str
    version_description: str
    created_by: PromptAuthor | None
    created_at: dt.datetime
    is_current: bool


class PromptNotFoundError(Exception):
    pass


BRAND_NAME_MAX_LENGTH = 200
KEYWORD_MAX_LENGTH = 100
MAX_KEYWORDS_PER_TEAM = 200
BRAND_DOMAIN_MAX_LENGTH = 253


class BrandKind(LabeledStrEnum):
    OWN = "own", "Own"
    COMPETITOR = "competitor", "Competitor"
    PUBLISHER = "publisher", "Publisher"
    UNKNOWN = "unknown", "Unknown"


class BrandStatus(LabeledStrEnum):
    SUGGESTED = "suggested", "Suggested"
    CONFIRMED = "confirmed", "Confirmed"
    IGNORED = "ignored", "Ignored"


class BrandSource(LabeledStrEnum):
    CITATIONS = "citations", "Citations"
    MANUAL = "manual", "Manual"


@frozen
class Brand:
    """One company in the team's brand catalog, keyed by its registrable domain."""

    id: str
    name: str
    domain: str
    kind: BrandKind
    status: BrandStatus
    source: BrandSource
    aliases: tuple[str, ...]
    created_at: dt.datetime
    updated_at: dt.datetime | None


@frozen
class BrandUpdate:
    """A partial edit of one brand. None leaves the field as it is."""

    name: str | None = None
    kind: BrandKind | None = None
    status: BrandStatus | None = None
    aliases: tuple[str, ...] | None = None


@frozen
class BrandCreate:
    """A brand a person adds to the catalog. `domain` may be a URL or a host; it is stored as its registrable domain."""

    domain: str
    kind: BrandKind
    name: str | None = None
    aliases: tuple[str, ...] = ()


@frozen
class BrandSyncResult:
    domains: int
    created: int


class BrandNotFoundError(Exception):
    pass


class BrandCreateError(Exception):
    """The brand cannot be added. The message is safe to show the user."""


@frozen
class EngineSetting:
    """One engine as the project runs it. `available` is false when the deployment cannot run the engine,
    for example without the API key it needs, and then it never runs whatever `enabled` says."""

    engine: str
    mode: CheckMode
    available: bool
    enabled: bool
    frequency: CheckFrequency


@frozen
class EngineSettingUpdate:
    """A partial edit of one engine's setting. None leaves the field as it is."""

    enabled: bool | None = None
    frequency: CheckFrequency | None = None


class EngineNotFoundError(Exception):
    pass


class PromptUpdateError(Exception):
    """The edit is not allowed in the prompt's current state. The message is safe to show the user."""


class PromptTextConflictError(Exception):
    """The new text matches another prompt in the set. The message is safe to show the user."""


class PromptSuggestionError(Exception):
    """Prompt suggestions could not be produced. The message is safe to show the user."""


class PromptCircle(LabeledStrEnum):
    """Where a prompt sits between the buyer, the brand and its competitors."""

    DIFFERENTIATION = "differentiation"
    BATTLEGROUND = "battleground"
    VULNERABILITY = "vulnerability"
    TABLE_STAKES = "table_stakes"
    BRANDED = "branded"


class FunnelStage(LabeledStrEnum):
    TOP = "top"
    MIDDLE = "middle"
    BOTTOM = "bottom"


@frozen
class PromptSuggestionRequest:
    domain: str
    brand: str = ""
    description: str = ""
    competitors: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    count: int = 20


@frozen
class PromptSuggestion:
    prompt: str
    topic: str
    circle: PromptCircle
    funnel_stage: FunnelStage
    branded: bool
    reason: str


class SuggestionJobStatus(LabeledStrEnum):
    """The state of a prompt or keyword suggestion job."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


@frozen
class PromptSuggestionJob:
    id: str
    status: SuggestionJobStatus
    suggestions: tuple[PromptSuggestion, ...] = ()
    error: str = ""


class PromptSuggestionJobNotFoundError(Exception):
    pass


@frozen
class RankedBrand:
    """How often answers named one brand: the project's own, or a competitor derived from the
    domains the engines cite."""

    domain: str
    name: str
    is_target: bool
    answers_mentioning: int
    visibility: float | None
    previous_visibility: float | None
    positive_share: float | None


@frozen
class RankedBrandDay:
    """One brand's visibility on one day."""

    date: dt.date
    domain: str
    answers: int
    visibility: float | None


@frozen
class RankedDomain:
    """A registrable domain the engines cited, with how many answers and distinct pages."""

    domain: str
    answers: int
    share_of_answers: float
    urls: int
    is_target: bool
    is_competitor: bool


@frozen
class RankedPage:
    """A page the engines cited."""

    url: str
    answers: int
    share_of_answers: float
    is_target: bool


@frozen
class PromptSetRankings:
    """Brand visibility against competitors, and the domains and pages the engines cite, over the
    last `days` days."""

    days: int
    window_from: dt.date
    window_to: dt.date
    branded: BrandedSegment
    answers: int
    competitors_confirmed: bool
    brands: tuple[RankedBrand, ...]
    daily: tuple[RankedBrandDay, ...]
    top_domains: tuple[RankedDomain, ...]
    top_pages: tuple[RankedPage, ...]


MAX_KEYWORD_MODIFIERS = 50
MAX_MODIFIER_EXAMPLES = 3


@frozen
class Keyword:
    id: str
    keyword: str
    created_at: dt.datetime


@frozen
class KeywordCreateResult:
    created: int
    skipped: int


class KeywordNotFoundError(Exception):
    pass


class KeywordLimitError(Exception):
    """The request would take the project past its keyword cap. The message is safe to show the user."""


MAX_SUGGESTED_KEYWORDS = 50
# Suggestions count engine searches over the most recent checks of this window, which bounds the read.
KEYWORD_SUGGESTION_SEARCH_DAYS = 30
KEYWORD_SUGGESTION_SEARCH_CHECKS = 2000


class KeywordSuggestionError(Exception):
    """Keyword suggestions could not be produced. The message is safe to show the user."""


@frozen
class KeywordSuggestionRequest:
    domain: str
    brand: str = ""
    description: str = ""
    count: int = 20


@frozen
class KeywordSuggestion:
    keyword: str
    reason: str
    # Recent answers whose web searches contain the keyword, counted by PostHog rather than the model.
    searched_checks: int


@frozen
class KeywordSuggestionJob:
    id: str
    status: SuggestionJobStatus
    suggestions: tuple[KeywordSuggestion, ...] = ()
    error: str = ""


class KeywordSuggestionJobNotFoundError(Exception):
    pass


@frozen
class KeywordReportRow:
    """How one keyword shows up across the answered checks in the window. Each rate is None when its
    denominator is zero."""

    keyword: str
    prompts: int
    prompt_checks: int
    prompt_mention_rate: float | None
    prompt_cited_rate: float | None
    searched_checks: int
    searched_rate: float | None
    searched_cited_rate: float | None
    answer_checks: int
    answer_rate: float | None
    uses_per_answer: float | None
    answer_mention_rate: float | None
    avg_citation_position: float | None
    median_first_mention_depth: float | None


@frozen
class KeywordReport:
    days: int
    window_from: dt.date
    window_to: dt.date
    answers: int
    brand_names: tuple[str, ...]
    keywords: tuple[KeywordReportRow, ...]


class ModifierKind(LabeledStrEnum):
    FRESHNESS = "freshness", "Freshness"
    PRICING = "pricing", "Pricing"
    COMPARISON = "comparison", "Comparison"
    DOCS = "docs", "Docs"
    SITE = "site", "Site"
    COMPETITOR = "competitor", "Competitor"
    OTHER = "other", "Other"


@frozen
class ModifierEngineCount:
    engine: str
    answers: int


@frozen
class KeywordModifier:
    """A word or two-word phrase the engines searched for that the prompt did not contain."""

    term: str
    kind: ModifierKind
    answers: int
    share: float
    cited_rate: float | None
    engines: tuple[ModifierEngineCount, ...]
    example_searches: tuple[str, ...]


@frozen
class KeywordModifierReport:
    days: int
    window_from: dt.date
    window_to: dt.date
    keyword: str | None
    answers: int
    baseline_cited_rate: float | None
    modifiers: tuple[KeywordModifier, ...]


@frozen
class VisibilityDashboard:
    """A dashboard created for the team's AI visibility."""

    id: int
    name: str


SETUP_PROMPT_COUNT = 20
SETUP_KEYWORD_COUNT = 20
# A project that already has this many active prompts or keywords keeps its own list, and setup skips the step.
SETUP_ENOUGH_PROMPTS = 10
SETUP_ENOUGH_KEYWORDS = 10
SETUP_WEBSITE_DAYS = 7
MAX_SETUP_WEBSITES = 5


class WebsiteSource(LabeledStrEnum):
    """Where PostHog found a website the project may be about."""

    OWN_BRAND = "own_brand"
    APP_URLS = "app_urls"
    RECORDING_DOMAINS = "recording_domains"
    PAGEVIEWS = "pageviews"


@frozen
class WebsiteCandidate:
    domain: str
    source: WebsiteSource
    # Pageviews on the domain over the last SETUP_WEBSITE_DAYS days, only for the pageviews source.
    pageviews: int | None = None


@frozen
class SetupContext:
    """What PostHog already knows about the project, so setup can start from it."""

    websites: tuple[WebsiteCandidate, ...]
    own_domains: tuple[str, ...]
    active_prompts: int
    keywords: int
    has_checks: bool
    ai_data_processing_approved: bool
    first_run_available: bool
    # The engines as the project runs them now, defaults included, for choosing which ones to track.
    engines: tuple[EngineSetting, ...]
    # How many prompts setup asks for, so a client can show how many checks one run makes.
    prompt_target: int
    # The window, in days, of the pageview hosts among the websites.
    website_days: int


class SetupStep(LabeledStrEnum):
    BRAND = "brand"
    PROMPTS = "prompts"
    KEYWORDS = "keywords"
    FIRST_RUN = "first_run"


class SetupStepStatus(LabeledStrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


@frozen
class SetupStepState:
    step: SetupStep
    status: SetupStepStatus
    # How many prompts or keywords the step added.
    added: int = 0
    detail: str = ""


@frozen
class SetupRequest:
    domain: str
    brand: str = ""
    description: str = ""
    # Each check is a paid call to every enabled engine, so the first run is queued only when asked for.
    run_first_check: bool = False
    # The engines to track. Every other engine is turned off. None keeps the current settings.
    engines: tuple[str, ...] | None = None
    # Queue the first run and nothing else: no brand, prompts or keywords, and no engine change.
    only_first_run: bool = False


@frozen
class SetupJob:
    id: str
    status: SuggestionJobStatus
    steps: tuple[SetupStepState, ...] = ()
    error: str = ""


class SetupJobNotFoundError(Exception):
    pass


class SetupAlreadyRunningError(Exception):
    """The team already has a setup job pending. `job_id` is that job, so a client can follow it instead."""

    def __init__(self, job_id: str) -> None:
        super().__init__(job_id)
        self.job_id = job_id


class SetupRequestError(Exception):
    """The setup request cannot start. The message is safe to show the user."""
