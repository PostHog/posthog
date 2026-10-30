"""Boundary contracts for the AEO product.

The only data shapes other modules may consume. Never expose ORM instances.
"""

from __future__ import annotations

import datetime as dt

from posthog.dataclasses import frozen


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


AEO_CITATION_TRACKING_FLAG = "aeo-citation-tracking"
PROMPT_TOPIC_MAX_LENGTH = 200
PROMPT_VERSION_DESCRIPTION_MAX_LENGTH = 400


@frozen
class PromptEngineCheck:
    """The most recent check of one prompt against one answer engine."""

    engine: str
    cited: bool
    check_failed: bool
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


@frozen
class PromptImport:
    prompt: str
    topic: str = ""
    external_visibility: float | None = None


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


class PromptUpdateError(Exception):
    """The edit is not allowed in the prompt's current state. The message is safe to show the user."""


class PromptTextConflictError(Exception):
    """The new text matches another prompt in the set. The message is safe to show the user."""
