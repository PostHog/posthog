"""Dataclasses passed across the channel-summary activity/workflow boundaries.

Datetimes cross as ISO-8601 strings so the payloads stay on Temporal's default
JSON converter.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SummaryCoordinatorInput:
    pass


@dataclass
class SummaryCoordinatorOutput:
    due_count: int
    started_count: int
    skipped_count: int


@dataclass
class ChannelSummaryInput:
    team_id: int
    account_id: str
    account_name: str
    slack_channel_id: str
    cadence: str
    period_start: str
    period_end: str


@dataclass
class CollectDueChannelsOutput:
    due: list[ChannelSummaryInput] = field(default_factory=list)


@dataclass
class ChannelSummaryOutput:
    # None when the period had no messages (no row written, no LLM call).
    summary_id: str | None
    message_count: int
