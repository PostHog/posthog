"""Writes the shared platform's check history to ClickHouse.

One row per check. The table is append-only and TTL'd, so a check that confirmed the alert is
recorded alongside the ones that moved it, and nothing has to decide which checks are worth
keeping.

ClickHouse has no unique constraint, so a retried batch inserts a second row for the same
evaluation. `expires_at` is the ReplacingMergeTree version column, so a merge keeps the later
one, and a reader deduplicates on `(alert_id, evaluation_key)` rather than assuming a merge has
run.
"""

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.dataclasses import frozen

from products.alerts.backend.models.platform_alert_events_sql import PLATFORM_ALERT_EVENTS_TABLE

logger = structlog.get_logger(__name__)

_COLUMNS = (
    "team_id",
    "configuration_id",
    "alert_id",
    "grouping_key",
    "evaluation_key",
    "kind",
    "alert_name",
    "previous_state",
    "state",
    "value",
    "labels",
    "condition_snapshot",
    "source_config_snapshot",
    "query_duration_ms",
    "error_message",
    "consecutive_failures",
    "muted_notification",
    "occurred_at",
)

_INSERT_SQL = f"INSERT INTO {PLATFORM_ALERT_EVENTS_TABLE} ({', '.join(_COLUMNS)}) VALUES"


@frozen
class PlatformAlertEventRow:
    """One check, as the history table stores it.

    The three snapshots make the row self-sufficient: a threshold edited between a check and a
    retried send cannot change what the message claims was breached, and a rename cannot make one
    thread contradict itself.
    """

    team_id: int
    configuration_id: UUID
    alert_id: UUID
    grouping_key: str
    evaluation_key: str
    kind: str
    alert_name: str
    previous_state: str
    state: str
    value: float | None
    labels: dict[str, str]
    condition_snapshot: dict[str, Any]
    source_config_snapshot: dict[str, Any]
    query_duration_ms: int | None
    error_message: str | None
    consecutive_failures: int
    muted_notification: str
    occurred_at: datetime

    def as_row(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "configuration_id": self.configuration_id,
            "alert_id": self.alert_id,
            "grouping_key": self.grouping_key,
            "evaluation_key": self.evaluation_key,
            "kind": self.kind,
            "alert_name": self.alert_name,
            "previous_state": self.previous_state,
            "state": self.state,
            "value": self.value,
            "labels": self.labels,
            "condition_snapshot": json.dumps(self.condition_snapshot),
            "source_config_snapshot": json.dumps(self.source_config_snapshot),
            "query_duration_ms": self.query_duration_ms,
            "error_message": self.error_message or "",
            "consecutive_failures": self.consecutive_failures,
            "muted_notification": self.muted_notification,
            "occurred_at": self.occurred_at,
        }


def insert_events(team_id: int, rows: Sequence[PlatformAlertEventRow]) -> int:
    """Records a batch's history. Returns how many rows it wrote.

    Never raises. History is a record of what the platform decided, not a step in deciding it, so
    a ClickHouse outage must not fail a batch whose state and schedule are already written. The
    cost of a failure is a gap a comparison sees, which is what the counter here is for.
    """
    if not rows:
        return 0
    try:
        sync_execute(_INSERT_SQL, [row.as_row() for row in rows], team_id=team_id)
    except Exception as error:
        logger.exception(
            "Failed to record platform alert check history",
            team_id=team_id,
            rows=len(rows),
            error=str(error),
        )
        return 0
    return len(rows)
