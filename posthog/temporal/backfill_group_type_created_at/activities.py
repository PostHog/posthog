from datetime import UTC, datetime
from uuid import uuid4

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.models import Team
from posthog.models.group_type_mapping import invalidate_group_types_cache
from posthog.persons_db import persons_db_connection
from posthog.sync import database_sync_to_async
from posthog.temporal.backfill_group_type_created_at.types import (
    ApplyBackfillInput,
    BackfillGroupTypeCreatedAtError,
    GroupTypeUpdate,
    PlanBackfillInput,
)
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import get_write_only_logger

LOGGER = get_write_only_logger()

# $group_0..$group_4 are the materialized group key columns on the events table.
GROUP_TYPE_INDEXES = range(5)


@activity.defn(name="plan-group-type-created-at-backfill")
async def plan_group_type_created_at_backfill(input: PlanBackfillInput) -> dict:
    """Build the list of created_at corrections without writing anything.

    Resolves the team's project (and its sibling environments), reads the group type
    mappings from Postgres, finds the earliest event timestamp per group column in
    ClickHouse, and proposes lowering created_at to that earliest timestamp wherever
    the current value is masking real events.
    """
    bind_contextvars(team_id=input.team_id)
    logger = LOGGER.bind()

    @database_sync_to_async
    def fetch_mappings() -> dict:
        try:
            team = Team.objects.get(id=input.team_id)
        except Team.DoesNotExist:
            # Fatal: a missing team won't appear on retry. The workflow marks this type
            # non-retryable so Temporal fails fast instead of spinning.
            raise BackfillGroupTypeCreatedAtError(f"Team {input.team_id} not found")

        project_id = team.project_id
        # Group types are project-scoped, but events carry team_id, so the earliest
        # event must be found across every environment in the project.
        team_ids = list(Team.objects.filter(project_id=project_id).values_list("id", flat=True))
        # Read from the writer (matching the original PERSONS_DB_FOR_WRITE) so the plan sees the
        # current created_at, consistent with the writer-side guard in the apply step.
        with persons_db_connection(writer=True) as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT group_type, group_type_index, created_at FROM posthog_grouptypemapping WHERE project_id = %s",
                [project_id],
            )
            mappings = [
                {"group_type": group_type, "group_type_index": index, "created_at": created_at}
                for group_type, index, created_at in cursor.fetchall()
            ]
        return {"project_id": project_id, "team_ids": team_ids, "mappings": mappings}

    pg = await fetch_mappings()
    project_id = pg["project_id"]
    team_ids = pg["team_ids"]
    mappings = pg["mappings"]

    result: dict = {
        "team_id": input.team_id,
        "project_id": project_id,
        "team_ids_in_project": team_ids,
        "updates": [],
        "skipped": [],
    }

    if not mappings:
        logger.info("No group type mappings for project", project_id=project_id)
        return result

    earliest = await _fetch_earliest_group_timestamps(team_ids)
    result["updates"], result["skipped"] = _build_backfill_plan(mappings, earliest)

    logger.info(
        "Planned group type created_at backfill",
        project_id=project_id,
        updates=len(result["updates"]),
        skipped=len(result["skipped"]),
    )
    return result


def _build_backfill_plan(
    mappings: list[dict], earliest: dict[int, datetime]
) -> tuple[list[GroupTypeUpdate], list[dict]]:
    """Decide which mappings need a lower created_at, given the earliest event per group.

    A mapping is updated only when it currently masks real events — i.e. it has a
    created_at that is strictly later than the earliest event carrying that group.
    """
    updates: list[GroupTypeUpdate] = []
    skipped: list[dict] = []

    for mapping in mappings:
        index = mapping["group_type_index"]
        group_type = mapping["group_type"]
        created_at = mapping["created_at"]
        earliest_ts = earliest.get(index)

        if created_at is None:
            # No created_at means HogQL never masks this group — nothing to fix.
            skipped.append({"group_type_index": index, "group_type": group_type, "reason": "created_at already null"})
            continue
        if earliest_ts is None:
            skipped.append(
                {"group_type_index": index, "group_type": group_type, "reason": "no events carry this group"}
            )
            continue
        if earliest_ts >= created_at:
            skipped.append(
                {
                    "group_type_index": index,
                    "group_type": group_type,
                    "reason": "created_at already at or before earliest event",
                }
            )
            continue

        updates.append(
            {
                "group_type": group_type,
                "group_type_index": index,
                "current_created_at": created_at.isoformat(),
                "new_created_at": earliest_ts.isoformat(),
            }
        )

    return updates, skipped


async def _fetch_earliest_group_timestamps(team_ids: list[int]) -> dict[int, datetime]:
    """Earliest event timestamp per $group_N column across the given teams, in UTC.

    Returns only indexes that actually have at least one event carrying the group;
    timestamps are floored to the second, which can only widen visibility (never mask).
    """
    select_exprs = ", ".join(
        f"toUnixTimestamp(minIf(timestamp, notEmpty(`$group_{i}`))) AS min_{i}, "
        f"countIf(notEmpty(`$group_{i}`)) AS cnt_{i}"
        for i in GROUP_TYPE_INDEXES
    )
    query = f"""
        SELECT {select_exprs}
        FROM events
        WHERE team_id IN %(team_ids)s
        FORMAT JSONEachRow
    """

    async with get_client() as client:
        rows = await client.read_query_as_jsonl(
            query,
            query_parameters={"team_ids": tuple(team_ids)},
            query_id=str(uuid4()),
        )

    result: dict[int, datetime] = {}
    if not rows:
        return result

    row = rows[0]
    for i in GROUP_TYPE_INDEXES:
        if int(row[f"cnt_{i}"]) > 0:
            result[i] = datetime.fromtimestamp(int(row[f"min_{i}"]), tz=UTC)
    return result


@activity.defn(name="apply-group-type-created-at-backfill")
async def apply_group_type_created_at_backfill(input: ApplyBackfillInput) -> dict:
    """Write the planned created_at values to Postgres and invalidate the cache.

    The group type mapping table is personhog-owned (managed=False) but its created_at
    has no personhog RPC, so we write directly to the persons DB through the off-ORM
    connection util — then bust the group-types cache so HogQL reads the new value
    instead of the stale masked one.
    """
    bind_contextvars(project_id=input.project_id)
    logger = LOGGER.bind()

    @database_sync_to_async
    def apply() -> int:
        updated = 0
        with persons_db_connection(writer=True, autocommit=True) as conn:
            for update in input.updates:
                new_created_at = datetime.fromisoformat(update["new_created_at"])
                # created_at > %s enforces the "only lower" invariant at the DB level, so a
                # re-run — or the ingestion fix landing between plan and apply — can never
                # raise created_at back up.
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE posthog_grouptypemapping SET created_at = %s "
                        "WHERE project_id = %s AND group_type_index = %s AND created_at > %s",
                        [new_created_at, input.project_id, update["group_type_index"], new_created_at],
                    )
                    updated += cursor.rowcount
        invalidate_group_types_cache(input.project_id)
        return updated

    updated = await apply()
    logger.info("Applied group type created_at backfill", project_id=input.project_id, updated=updated)
    return {"updated": updated}
