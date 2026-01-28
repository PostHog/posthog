"""Dagster job to automatically sync person_id overrides.

This job detects distinct_ids where the resolved person_id (using overrides) differs
from the person_id in person_distinct_id2, indicating that some overrides exist but
others may be missing. It then ensures ALL distinct_ids for affected persons have
the correct overrides.
"""

from typing import Optional

import dagster
import pydantic

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.dags.common import JobOwners
from posthog.models import Team


class SyncPersonOverridesConfig(dagster.Config):
    """Configuration for the sync person overrides job."""

    team_id: int = pydantic.Field(description="Team ID to process")
    dry_run: bool = pydantic.Field(
        default=True,
        description="If true, don't actually insert, just log what would be inserted",
    )


def get_mismatched_person_ids(team: Team) -> list[str]:
    """Find person_ids where events.person_id differs from pdi.person_id.

    This identifies persons where at least one override exists but possibly
    not all distinct_ids have overrides yet.

    Returns list of person_ids that need to be checked.
    """
    result = execute_hogql_query(
        """
        SELECT DISTINCT person_id
        FROM events
        WHERE person_id != pdi.person_id
        """,
        team=team,
    )
    return [str(row[0]) for row in result.results] if result.results else []


def get_all_distinct_ids_for_person(team_id: int, person_id: str) -> list[tuple[str, int]]:
    """Get ALL distinct_ids mapped to a person_id in person_distinct_id2."""
    result = sync_execute(
        """
        SELECT
            distinct_id,
            max(version) as max_version
        FROM person_distinct_id2
        WHERE team_id = %(team_id)s
        GROUP BY distinct_id
        HAVING argMax(person_id, version) = %(person_id)s
          AND argMax(is_deleted, version) = 0
        """,
        {"team_id": team_id, "person_id": person_id},
    )
    return [(row[0], int(row[1])) for row in result] if result else []


def get_existing_override(team_id: int, distinct_id: str) -> Optional[tuple[str, int]]:
    """Check if an override already exists."""
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
def sync_person_overrides_op(
    context: dagster.OpExecutionContext,
    config: SyncPersonOverridesConfig,
) -> None:
    """
    Automatically detect and fix missing person_id overrides.

    1. Use HogQL to find person_ids where events.person_id != pdi.person_id
       (indicating some overrides exist but possibly not all)
    2. For each affected person_id, get all their distinct_ids from pdi2
    3. Insert overrides for any distinct_ids that don't have them yet
    """
    team = Team.objects.get(id=config.team_id)

    context.log.info(f"Finding mismatched person_ids for team {config.team_id}")
    context.log.info(f"Dry run: {config.dry_run}")

    # Step 1: Find person_ids with mismatches
    mismatched_person_ids = get_mismatched_person_ids(team)
    context.log.info(f"Found {len(mismatched_person_ids)} person_ids with mismatches")

    if not mismatched_person_ids:
        context.log.info("No mismatches found, nothing to do")
        return

    # Batch of overrides to insert: (team_id, distinct_id, person_id, version)
    pending_overrides: list[tuple[int, str, str, int]] = []

    for person_id in mismatched_person_ids:
        # Step 2: Get ALL distinct_ids mapped to this person
        all_distinct_ids = get_all_distinct_ids_for_person(config.team_id, person_id)
        context.log.info(f"Person {person_id[:8]}... has {len(all_distinct_ids)} distinct_ids")

        # Step 3: Collect overrides for each distinct_id that doesn't have one
        for distinct_id, version in all_distinct_ids:
            existing = get_existing_override(config.team_id, distinct_id)
            if existing:
                continue

            # Use version > 0 so it gets picked up by the overrides MV
            new_version = max(version, 1)

            if config.dry_run:
                context.log.info(f"  [DRY RUN] Would insert -> distinct_id={distinct_id}, person_id={person_id[:8]}...")
            else:
                pending_overrides.append((config.team_id, distinct_id, person_id, new_version))
                context.log.info(f"  Queued: {distinct_id} -> {person_id[:8]}...")

    # Insert all overrides at once
    if not config.dry_run and pending_overrides:
        insert_override_batch(pending_overrides)
        context.log.info(f"Inserted {len(pending_overrides)} overrides")
    elif config.dry_run:
        context.log.info(f"[DRY RUN] Would have inserted {len(pending_overrides)} overrides")


@dagster.job(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def sync_person_overrides_job():
    """Job to automatically sync person_id overrides for a team."""
    sync_person_overrides_op()
