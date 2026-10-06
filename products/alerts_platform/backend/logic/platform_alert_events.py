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
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    AnnouncedTransition,
    EvaluationAnnouncement,
)
from products.alerts_platform.backend.models.platform_alert_events_sql import PLATFORM_ALERT_EVENTS_TABLE

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
    # The firing this check concerned, which on a resolve is the one it ended. The alert row
    # holds the firing it is in now, so the two differ on exactly that check.
    episode_started_at: datetime | None
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
        """The row as ClickHouse takes it, derived from the fields so a new one cannot be missed.

        Only the three the wire needs in another shape are named.
        """
        return {f.name: getattr(self, f.name) for f in fields(self)} | {
            "condition_snapshot": json.dumps(self.condition_snapshot),
            "source_config_snapshot": json.dumps(self.source_config_snapshot),
            "error_message": self.error_message or "",
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
        # `sync_execute` requires both tags. The platform product rather than a source's, because
        # the table serves every source and the write is the platform's own bookkeeping.
        tag_queries(product=Product.PLATFORM_AND_SUPPORT, feature=Feature.ALERTING)
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


_ANNOUNCEMENT_SQL = f"""
SELECT grouping_key, kind, episode_started_at, value, labels, condition_snapshot,
       source_config_snapshot, error_message, occurred_at, alert_name, consecutive_failures
FROM {PLATFORM_ALERT_EVENTS_TABLE}
WHERE team_id = %(team_id)s
  AND configuration_id = %(configuration_id)s
  AND evaluation_key = %(evaluation_key)s
  AND kind != %(check_kind)s
ORDER BY grouping_key, occurred_at DESC
LIMIT 1 BY grouping_key
"""


def announcement(team_id: int, configuration_id: str, evaluation_key: str) -> EvaluationAnnouncement | None:
    """What one evaluation left for a destination to say, or None when it announced nothing.

    Rows whose kind is `CHECK` are excluded here rather than in the caller. They are recorded so
    a comparison can read every check, and they say nothing, so a message built from one would
    have no headline.

    `LIMIT 1 BY grouping_key` is the read's own deduplication. The insert carries a token the
    engine drops a repeat under, but it only remembers a bounded window of them, so a retry far
    enough behind writes a second row for a group. The newest is the one this evaluation meant.
    """
    tag_queries(product=Product.PLATFORM_AND_SUPPORT, feature=Feature.ALERTING)
    rows = sync_execute(
        _ANNOUNCEMENT_SQL,
        {
            "team_id": team_id,
            "configuration_id": configuration_id,
            "evaluation_key": evaluation_key,
            "check_kind": AlertEventKind.CHECK.value,
        },
        team_id=team_id,
    )
    if not rows:
        return None

    transitions = tuple(
        AnnouncedTransition(
            grouping_key=grouping_key,
            kind=AlertEventKind(kind),
            episode_started_at=episode_started_at,
            value=value,
            labels=dict(labels or {}),
            condition=_snapshot(condition_snapshot),
            source_config=_snapshot(source_config_snapshot),
            error_message=error_message or None,
            occurred_at=occurred_at,
        )
        for grouping_key, kind, episode_started_at, value, labels, condition_snapshot, source_config_snapshot, error_message, occurred_at, _, _ in rows
    )
    # Evaluation-level, and the same on every row of one evaluation, so the first row carries it.
    *_, alert_name, consecutive_failures = rows[0]
    return EvaluationAnnouncement(
        configuration_id=configuration_id,
        alert_name=alert_name,
        consecutive_failures=consecutive_failures,
        transitions=transitions,
    )


def _snapshot(raw: str) -> dict[str, Any]:
    """A snapshot column the writer may have left empty, or that predates the field it holds."""
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except ValueError:
        return {}
    return loaded if isinstance(loaded, dict) else {}
