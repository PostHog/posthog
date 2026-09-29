"""Writes the shared platform's check history to ClickHouse.

One row per check. The table is append-only and TTL'd, so a check that confirmed the alert is
recorded alongside the ones that moved it, and nothing has to decide which checks are worth
keeping.

ClickHouse has no unique constraint, so the insert carries a deduplication token instead. The
token names the batch by its contents, and the replicated engine drops a second insert that
arrives under a token it has already seen. A reader still deduplicates on
`(alert_id, evaluation_key)`, because the token only covers a retry of the same batch and the
engine only remembers a bounded window of them.
"""

import json
import hashlib
from collections.abc import Sequence
from dataclasses import fields
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.dataclasses import frozen

from products.alerts.backend.models.platform_alert_events_sql import PLATFORM_ALERT_EVENTS_TABLE

logger = structlog.get_logger(__name__)


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


# Derived from the row rather than listed again, so a new column cannot reach the dataclass and
# miss the insert.
_COLUMNS = tuple(f.name for f in fields(PlatformAlertEventRow))
_INSERT_SQL = f"INSERT INTO {PLATFORM_ALERT_EVENTS_TABLE} ({', '.join(_COLUMNS)}) VALUES"


def _deduplication_token(team_id: int, rows: Sequence[PlatformAlertEventRow]) -> str:
    """Names a batch by the evaluations in it, so a retry of that batch carries the same name.

    The activity is retried by Temporal, and a retry that follows a committed transaction can
    reach an insert the first attempt had already landed. `insert_deduplication_token` makes the
    replicated engine drop the second one.

    Built from the batch's contents rather than from `(team_id, cutoff)`, because two sources can
    record for one team at one cutoff and a token those two shared would silently drop the second
    source's rows.

    The grouping key is in the digest because one configuration writes one row per group once a
    source groups its results. Without it, two batches that hold the same configurations and
    evaluation keys but different groups take the same name, and the engine drops the second one
    whole.
    """
    digest = hashlib.sha256(str(team_id).encode())
    for configuration_id, grouping_key, evaluation_key in sorted(
        (str(row.configuration_id), row.grouping_key, row.evaluation_key) for row in rows
    ):
        digest.update(b"\0")
        digest.update(configuration_id.encode())
        digest.update(b"\0")
        digest.update(grouping_key.encode())
        digest.update(b"\0")
        digest.update(evaluation_key.encode())
    return digest.hexdigest()


def insert_events(team_id: int, rows: Sequence[PlatformAlertEventRow]) -> int:
    """Records a batch's history. Returns how many rows it wrote.

    Never raises. History is a record of what the platform decided, not a step in deciding it, so
    a ClickHouse outage must not fail a batch whose state and schedule are already written. The
    cost of a failure is a gap a comparison sees, which is what the counter here is for.
    """
    if not rows:
        return 0
    try:
        # No product tag: the history table serves every source, so the write belongs to the
        # shared platform rather than to one of them.
        tag_queries(feature=Feature.ALERTING)
        sync_execute(
            _INSERT_SQL,
            [row.as_row() for row in rows],
            settings={"insert_deduplication_token": _deduplication_token(team_id, rows)},
            team_id=team_id,
        )
    except Exception as error:
        logger.exception(
            "Failed to record platform alert check history",
            team_id=team_id,
            rows=len(rows),
            error=str(error),
        )
        return 0
    return len(rows)
