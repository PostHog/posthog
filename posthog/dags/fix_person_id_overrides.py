"""Dagster job to insert person_id overrides for distinct_ids.

Given a list of "bugged" distinct_ids, for each one:
1. Find its person_id in person_distinct_id2
2. Find ALL other distinct_ids mapped to that same person_id
3. Insert ALL of them into person_distinct_id_overrides
"""

from typing import Optional

import dagster
import pydantic

from posthog.clickhouse.client import sync_execute
from posthog.dags.common import JobOwners


class FixPersonIdOverridesConfig(dagster.Config):
    """Configuration for the fix person_id overrides job."""

    team_id: int = pydantic.Field(description="Team ID to process")
    distinct_ids: str = pydantic.Field(description="Comma-separated list of bugged distinct_ids")
    dry_run: bool = pydantic.Field(
        default=True,
        description="If true, don't actually insert, just log what would be inserted",
    )


def get_person_id_from_pdi2(team_id: int, distinct_id: str) -> Optional[tuple[str, int]]:
    """Get the current person_id and version for a distinct_id from person_distinct_id2."""
    result = sync_execute(
        """
        SELECT
            argMax(person_id, version) as pid,
            max(version) as max_version
        FROM person_distinct_id2
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


def insert_override(team_id: int, distinct_id: str, person_id: str, version: int) -> None:
    """Insert a record into person_distinct_id_overrides."""
    sync_execute(
        """
        INSERT INTO person_distinct_id_overrides
        (team_id, distinct_id, person_id, is_deleted, version, _timestamp, _offset, _partition)
        VALUES
        (%(team_id)s, %(distinct_id)s, %(person_id)s, 0, %(version)s, now(), 0, 0)
        """,
        {
            "team_id": team_id,
            "distinct_id": distinct_id,
            "person_id": person_id,
            "version": version,
        },
    )


@dagster.op
def fix_person_id_overrides_op(
    context: dagster.OpExecutionContext,
    config: FixPersonIdOverridesConfig,
) -> None:
    """
    For each bugged distinct_id:
    1. Find its person_id in person_distinct_id2
    2. Find ALL distinct_ids mapped to that person_id
    3. Insert ALL mappings into person_distinct_id_overrides
    """
    # Parse comma-separated distinct_ids
    bugged_distinct_ids = [d.strip() for d in config.distinct_ids.split(",") if d.strip()]

    context.log.info(f"Processing {len(bugged_distinct_ids)} bugged distinct_ids")
    context.log.info(f"Dry run: {config.dry_run}")

    # Track which person_ids we've already processed to avoid duplicates
    processed_person_ids: set[str] = set()

    for _i, bugged_distinct_id in enumerate(bugged_distinct_ids):
        # Step 1: Get person_id for this bugged distinct_id
        pdi2_result = get_person_id_from_pdi2(config.team_id, bugged_distinct_id)
        if not pdi2_result:
            context.log.warning(f"No person found for bugged distinct_id={bugged_distinct_id}")
            continue

        person_id, _ = pdi2_result

        # Skip if we already processed this person
        if person_id in processed_person_ids:
            context.log.info(f"Already processed person_id={person_id}... for distinct_id={bugged_distinct_id}")
            continue

        processed_person_ids.add(person_id)

        # Step 2: Get ALL distinct_ids mapped to this person
        all_distinct_ids = get_all_distinct_ids_for_person(config.team_id, person_id)
        context.log.info(
            f"Person {person_id}... has {len(all_distinct_ids)} distinct_ids: {', '.join(did for did, _ in all_distinct_ids)} "
        )

        # Step 3: Insert override for each distinct_id
        for distinct_id, version in all_distinct_ids:
            # Check if override already exists
            existing = get_existing_override(config.team_id, distinct_id)
            if existing:
                continue

            # Use version > 0 so it gets picked up by the overrides MV
            new_version = max(version, 1)

            if config.dry_run:
                context.log.info(f"  [DRY RUN] Would insert -> Distinct ID: {distinct_id}, Person ID: {person_id}...")
            else:
                insert_override(config.team_id, distinct_id, person_id, new_version)
                context.log.info(f"  Inserted: {distinct_id} -> {person_id}...")


@dagster.job(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def fix_person_id_overrides_job():
    """Job to insert person_id overrides for specified distinct_ids."""
    fix_person_id_overrides_op()
