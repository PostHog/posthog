"""Dagster job to automatically fix missing person_id overrides.

This job detects distinct_ids where the resolved person_id (using overrides) differs
from the person_id in person_distinct_id2, indicating that a problem has occurred
during ingestion, person merges, clickhouse migration, etc. (It has hard to know
which, after the fact).
"""

from typing import Optional

import dagster
import pydantic

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.dags.common import JobOwners
from posthog.models import Team


class FixMissingPersonOverridesConfig(dagster.Config):
    """Configuration for the fix missing person overrides job."""

    team_id: int = pydantic.Field(description="Team ID to process")
    dry_run: bool = pydantic.Field(
        default=True,
        description="If true, don't actually insert, just log what would be inserted",
    )
    min_date: Optional[str] = pydantic.Field(
        default=None,
        description="Optional minimum date for events query (ISO format, e.g. '2024-01-01')",
    )
    max_date: Optional[str] = pydantic.Field(
        default=None,
        description="Optional maximum date for events query (ISO format, e.g. '2024-12-31')",
    )


def get_mismatched_person_ids(
    team: Team,
    min_date: Optional[str] = None,
    max_date: Optional[str] = None,
) -> list[str]:
    """Find person_ids where events.person_id differs from pdi.person_id.

    This identifies persons where at least one override exists but possibly
    not all distinct_ids have overrides yet.

    Args:
        team: The team to query
        min_date: Optional minimum date filter (ISO format)
        max_date: Optional maximum date filter (ISO format)

    Returns list of person_ids that need to be checked.
    """
    from posthog.hogql import ast
    from posthog.hogql.parser import parse_select

    # Parse base query
    query = parse_select("SELECT DISTINCT person_id FROM events WHERE person_id != pdi.person_id")

    # Build date filter conditions
    date_conditions: list[ast.Expr] = []

    if min_date:
        date_conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=min_date),
            )
        )

    if max_date:
        date_conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Lt,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=max_date),
            )
        )

    # Add date conditions to the WHERE clause
    if date_conditions and query.where:
        query.where = ast.And(exprs=[query.where, *date_conditions])

    result = execute_hogql_query(query, team=team)
    return [str(row[0]) for row in result.results] if result.results else []


def get_missing_overrides_for_person_ids(team_id: int, person_ids: list[str]) -> list[tuple[str, str, int]]:
    """Get all (distinct_id, person_id, version) tuples that need overrides.

    For all given person_ids, finds their distinct_ids in pdi2 and filters out
    any that already have overrides.

    Returns list of (distinct_id, person_id, version) tuples that need to be inserted.
    """
    if not person_ids:
        return []

    # Get all distinct_ids for the given person_ids
    pdi2_result = sync_execute(
        """
        SELECT
            distinct_id,
            argMax(person_id, version) as current_person_id,
            max(version) as max_version
        FROM person_distinct_id2
        WHERE team_id = %(team_id)s
        GROUP BY distinct_id
        HAVING current_person_id IN %(person_ids)s
          AND argMax(is_deleted, version) = 0
        """,
        {"team_id": team_id, "person_ids": person_ids},
    )

    if not pdi2_result:
        return []

    # Get distinct_ids that already have overrides
    existing_overrides = sync_execute(
        """
        SELECT distinct_id
        FROM person_distinct_id_overrides
        WHERE team_id = %(team_id)s
        GROUP BY distinct_id
        HAVING argMax(is_deleted, version) = 0
        """,
        {"team_id": team_id},
    )

    existing_distinct_ids = {row[0] for row in existing_overrides} if existing_overrides else set()

    # Filter out distinct_ids that already have overrides
    return [(row[0], str(row[1]), int(row[2])) for row in pdi2_result if row[0] not in existing_distinct_ids]


def get_existing_override(team_id: int, distinct_id: str) -> Optional[tuple[str, int]]:
    """Check if an override already exists (used for testing)."""
    result = sync_execute(
        """
        SELECT
            argMax(person_id, version) as pid,
            max(version) as max_version
        FROM person_distinct_id_overrides
        WHERE team_id = %(team_id)s
          AND distinct_id = %(distinct_id)s
        GROUP BY distinct_id
        HAVING argMax(is_deleted, version) = 0
        """,
        {"team_id": team_id, "distinct_id": distinct_id},
    )
    if result and result[0]:
        return str(result[0][0]), int(result[0][1])
    return None


def insert_override_batch(overrides: list[tuple[int, str, str, int]]) -> None:
    """Insert a batch of records into person_distinct_id_overrides.

    Args:
        overrides: List of (team_id, distinct_id, person_id, version) tuples
    """
    if not overrides:
        return

    team_ids = [t[0] for t in overrides]
    distinct_ids = [t[1] for t in overrides]
    person_ids = [t[2] for t in overrides]
    versions = [t[3] for t in overrides]

    sync_execute(
        """
        INSERT INTO person_distinct_id_overrides
        (team_id, distinct_id, person_id, is_deleted, version, _timestamp, _offset, _partition)
        SELECT
            tupleElement(t, 1) as team_id,
            tupleElement(t, 2) as distinct_id,
            tupleElement(t, 3) as person_id,
            0 as is_deleted,
            tupleElement(t, 4) as version,
            now() as _timestamp,
            0 as _offset,
            0 as _partition
        FROM (
            SELECT arrayJoin(arrayZip(
                %(team_ids)s,
                %(distinct_ids)s,
                %(person_ids)s,
                %(versions)s
            )) as t
        )
        """,
        {
            "team_ids": team_ids,
            "distinct_ids": distinct_ids,
            "person_ids": person_ids,
            "versions": versions,
        },
    )


@dagster.op
def fix_missing_person_overrides_op(
    context: dagster.OpExecutionContext,
    config: FixMissingPersonOverridesConfig,
) -> None:
    """
    Automatically detect and fix missing person_id overrides.

    1. Use HogQL to find person_ids where events.person_id != pdi.person_id
       (indicating some overrides exist but possibly not all)
    2. Get all distinct_ids for those person_ids that don't have overrides yet (single query)
    3. Batch insert all missing overrides
    """
    team = Team.objects.get(id=config.team_id)

    context.log.info(f"Finding mismatched person_ids for team {config.team_id}")
    context.log.info(f"Dry run: {config.dry_run}")
    if config.min_date or config.max_date:
        context.log.info(f"Date range: {config.min_date or 'start'} to {config.max_date or 'end'}")

    # Step 1: Find person_ids with mismatches (1 HogQL query)
    mismatched_person_ids = get_mismatched_person_ids(team, config.min_date, config.max_date)
    context.log.info(f"Found {len(mismatched_person_ids)} person_ids with mismatches")

    if not mismatched_person_ids:
        context.log.info("No mismatches found, nothing to do")
        return

    # Step 2: Get all missing overrides in a single query
    missing_overrides = get_missing_overrides_for_person_ids(config.team_id, mismatched_person_ids)
    context.log.info(f"Found {len(missing_overrides)} distinct_ids missing overrides")

    if not missing_overrides:
        context.log.info("All distinct_ids already have overrides")
        return

    # Build the batch with version > 0 so it gets picked up by the overrides MV
    pending_overrides = [
        (config.team_id, distinct_id, person_id, max(version, 1))
        for distinct_id, person_id, version in missing_overrides
    ]

    if config.dry_run:
        for distinct_id, person_id, _version in missing_overrides:
            context.log.info(f"  [DRY RUN] Would insert -> distinct_id={distinct_id}, person_id={person_id[:8]}...")
        context.log.info(f"[DRY RUN] Would have inserted {len(pending_overrides)} overrides")
    else:
        # Step 3: Batch insert all missing overrides (1 query)
        insert_override_batch(pending_overrides)
        context.log.info(f"Inserted {len(pending_overrides)} overrides")


@dagster.job(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def fix_missing_person_overrides_job():
    """Job to automatically fix missing person_id overrides for a team."""
    fix_missing_person_overrides_op()
