"""Dataclasses passed across the ticket-pattern activity/workflow boundaries.

Datetimes cross as ISO-8601 strings so the payloads stay on Temporal's default JSON converter.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PatternsCoordinatorInput:
    pass


@dataclass(frozen=True)
class PatternsCoordinatorOutput:
    eligible_team_count: int
    detected_count: int


@dataclass(frozen=True)
class DetectionSettings:
    """One team's detection thresholds, already clamped to their allowed ranges."""

    lookback_minutes: int
    min_tickets: int
    min_requesters: int


@dataclass(frozen=True)
class EligibleTeam:
    team_id: int
    settings: DetectionSettings


@dataclass(frozen=True)
class CollectEligibleTeamsOutput:
    teams: list[EligibleTeam] = field(default_factory=list)


@dataclass(frozen=True)
class TicketCandidate:
    """One ticket as the model sees it: an id to group by, and the text to group on."""

    ticket_id: str
    # Distinct requesters are counted on this, so it must identify the customer and not the
    # ticket: the organization when we resolved one, else the person's distinct id.
    requester_key: str
    subject: str
    message: str


@dataclass(frozen=True)
class DetectedCluster:
    topic: str
    summary: str
    ticket_ids: list[str]
    requester_count: int


@dataclass(frozen=True)
class DetectOutput:
    team_id: int
    candidate_count: int
    clusters: list[DetectedCluster] = field(default_factory=list)
