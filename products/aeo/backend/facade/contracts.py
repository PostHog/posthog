"""Boundary contracts for the AEO product.

The only data shapes other modules may consume. Never expose ORM instances.
"""

from __future__ import annotations

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
    events_captured: int
    capture_failures: int
    error: str | None = None
