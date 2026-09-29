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
