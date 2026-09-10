"""Dataclasses passed across the ticket-pattern activity/workflow boundaries.

Datetimes cross as ISO-8601 strings so the payloads stay on Temporal's default JSON converter.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PatternCoordinatorInput:
    pass


@dataclass
class PatternCoordinatorOutput:
    eligible_count: int
    started_count: int
    skipped_count: int


@dataclass
class TeamPatternInput:
    team_id: int
    # The tick this run belongs to; the child id embeds it so overlapping ticks collapse.
    tick: str


@dataclass
class CollectEligibleTeamsOutput:
    teams: list[TeamPatternInput] = field(default_factory=list)


@dataclass
class TeamPatternOutput:
    opened: int = 0
    updated: int = 0
    suppressed: int = 0
    auto_resolved: int = 0
    baselines_refreshed: bool = False
