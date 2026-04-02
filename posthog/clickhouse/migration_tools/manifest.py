"""Shared data types for ClickHouse migration steps."""

from __future__ import annotations

from dataclasses import dataclass

ROLE_MAP: dict[str, str] = {
    "DATA": "data",
    "COORDINATOR": "coordinator",
    "INGESTION_EVENTS": "events",
    "INGESTION_SMALL": "small",
    "INGESTION_MEDIUM": "medium",
    "SHUFFLEHOG": "shufflehog",
    "ENDPOINTS": "endpoints",
    "LOGS": "logs",
    "ALL": "all",
    "OPS": "ops",
    "AI_EVENTS": "ai_events",
    "AUX": "aux",
}

VALID_NODE_ROLES = frozenset(ROLE_MAP.keys())


@dataclass
class ManifestStep:
    sql: str
    node_roles: list[str]
    comment: str = ""
    sharded: bool = False
    is_alter_on_replicated_table: bool = False
    clusters: list[str] | None = None
    affected_table: str | None = None
