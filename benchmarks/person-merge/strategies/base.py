"""Strategy interface every merge-implementation candidate implements.

A strategy owns its schema and its SQL. The harness only knows three verbs:
apply the schema, run one identify (which internally lands in one of the three
scenarios: neither / one / both), and resolve a distinct id to a person. The
oracle asserts scenario outcomes through `resolve` plus strategy-agnostic
invariant queries, so candidates are free to change storage layout entirely.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

import psycopg


@dataclass(frozen=True, kw_only=True)
class Emission:
    """One message the merge would publish downstream (Kafka -> ClickHouse).

    `contract` marks whether the message shape exists today ("current") or
    requires a ClickHouse-side change ("new"). The report aggregates both so
    the cost of preserving the current override contract stays visible.
    """

    topic: str
    contract: str  # "current" | "new"
    payload: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class MergeOutcome:
    scenario: str  # "neither" | "one" | "both" | "noop"
    person_id: int | None
    person_uuid: str | None
    emissions: list[Emission]
    retries: int = 0


@dataclass(frozen=True, kw_only=True)
class ResolvedPerson:
    person_id: int
    person_uuid: str
    properties: dict[str, Any]
    is_identified: bool
    version: int


class Strategy(Protocol):
    name: str
    # True when the strategy can emit one per-moved-mapping override message,
    # matching today's ClickHouse contract. Strategies that only support the
    # "new" contract must say so, and the report flags them.
    supports_current_contract: bool

    def schema_files(self) -> list[str]:
        """SQL files applied to a fresh database, in order."""
        ...

    def identify(
        self,
        conn: psycopg.Connection,
        team_id: int,
        target_distinct_id: str,
        anon_distinct_id: str,
    ) -> MergeOutcome:
        """Run one $identify: merge anon_distinct_id into target_distinct_id.

        Must be safe under concurrency (retry internally like production does)
        and must leave the database consistent on any exit.
        """
        ...

    def resolve(self, conn: psycopg.Connection, team_id: int, distinct_id: str) -> ResolvedPerson | None:
        """The read path: what person does this distinct id belong to now?"""
        ...
