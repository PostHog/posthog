from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from django.db import connections, models, transaction
from django.db.models import Exists, OuterRef

import structlog

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.temporal.health_checks.rollups.fill import DayFill
from posthog.temporal.health_checks.rollups.framework import DailyRollup

logger = structlog.get_logger(__name__)

WRITE_DATABASE = "default"
DELETE_BATCH_SIZE = 10_000

PUBLISH_STATEMENT_TIMEOUT = "10min"
PUBLISH_LOCK_TIMEOUT = "30s"


@frozen
class DayStats:
    row_count: int
    event_count: int


def _advisory_lock_key(rollup: type[DailyRollup]) -> str:
    return f"daily_rollup:{rollup.table()}"


def publish_day(rollup: type[DailyRollup], fill: DayFill) -> None:
    """Replace one day of the rollup with the filled rows, in one transaction.

    Readers on the replica see the old day or the new one, never a mix. The advisory lock is
    transaction-scoped, so it works behind PgBouncer and releases on commit or rollback.
    """
    table = rollup.table()
    column_list = ", ".join(rollup.columns)
    delete_sql = f"DELETE FROM {table} WHERE day = %s"
    copy_sql = f"COPY {table} ({column_list}) FROM STDIN"

    with transaction.atomic(using=WRITE_DATABASE), connections[WRITE_DATABASE].cursor() as cursor:
        cursor.execute(f"SET LOCAL statement_timeout = '{PUBLISH_STATEMENT_TIMEOUT}'")
        cursor.execute(f"SET LOCAL lock_timeout = '{PUBLISH_LOCK_TIMEOUT}'")
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [_advisory_lock_key(rollup)])
        cursor.execute(delete_sql, [fill.day])
        replaced_rows = cursor.rowcount
        with cursor.cursor.copy(copy_sql) as copy:
            for chunk in fill.chunks():
                copy.write(chunk)

    logger.info(
        "daily rollup published",
        table=table,
        day=fill.day.isoformat(),
        rows=fill.row_count,
        events=fill.event_count,
        replaced_rows=replaced_rows,
    )


def day_stats(rollup: type[DailyRollup], days: Sequence[dt.date]) -> dict[dt.date, DayStats]:
    """Row and event counts per published day. A day with no rows is absent from the result."""
    if not days:
        return {}
    rows = (
        rollup.model.objects.unscoped()  # type: ignore[attr-defined]
        .using(WRITE_DATABASE)
        .filter(day__in=list(days))
        .values("day")
        .annotate(row_count=models.Count("*"), event_count=models.Sum("event_count"))
        .order_by("day")
    )
    return {row["day"]: DayStats(row_count=row["row_count"], event_count=row["event_count"] or 0) for row in rows}


def _delete_in_batches(table: str, condition: str, params: list[dt.date | list[int]]) -> int:
    delete_sql = f"DELETE FROM {table} WHERE ctid = ANY(ARRAY(SELECT ctid FROM {table} WHERE {condition} LIMIT %s))"
    deleted = 0
    while True:
        with connections[WRITE_DATABASE].cursor() as cursor:
            cursor.execute(delete_sql, [*params, DELETE_BATCH_SIZE])
            batch = cursor.rowcount
        deleted += batch
        if batch < DELETE_BATCH_SIZE:
            return deleted


def delete_days_before(rollup: type[DailyRollup], cutoff: dt.date) -> int:
    deleted = _delete_in_batches(rollup.table(), "day < %s", [cutoff])
    logger.info("daily rollup retention", table=rollup.table(), cutoff=cutoff.isoformat(), deleted_rows=deleted)
    return deleted


def delete_rollup_rows_for_teams(model: type[models.Model], team_ids: Sequence[int]) -> int:
    """Delete every row of the given environments. Team deletion calls this, because no foreign key cascades."""
    if not team_ids:
        return 0
    return _delete_in_batches(model._meta.db_table, "team_id = ANY(%s)", [list(team_ids)])


def delete_rows_of_deleted_teams(rollup: type[DailyRollup]) -> int:
    """Delete the rows of environments that no longer exist.

    A fill that publishes while a team deletion runs can write rows after the deletion removed them.
    """
    deleted_team_ids = list(
        rollup.model.objects.unscoped()  # type: ignore[attr-defined]
        .using(WRITE_DATABASE)
        .filter(~Exists(Team.objects.filter(id=OuterRef("team_id"))))
        .values_list("team_id", flat=True)
        .distinct()
    )
    return delete_rollup_rows_for_teams(rollup.model, deleted_team_ids)
