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


@frozen
class PromptEngineStats:
    engine: str
    checks: int
    cited: int
    failed: int
    first_checked_at: dt.datetime
    last_checked_at: dt.datetime

    @property
    def citation_rate(self) -> float | None:
        answered = self.checks - self.failed
        return self.cited / answered if answered else None


@frozen
class PromptDailyEngineStats:
    date: dt.date
    engine: str
    checks: int
    cited: int
    failed: int


@frozen
class PromptStats:
    total_checks: int
    engines: tuple[PromptEngineStats, ...]
    daily_from: dt.date
    daily_to: dt.date
    daily: tuple[PromptDailyEngineStats, ...]


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


class PromptNotFoundError(Exception):
    pass
