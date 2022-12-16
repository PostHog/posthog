from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple

import structlog
from django.utils import timezone

from posthog.client import sync_execute
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER

logger = structlog.get_logger(__name__)
# Note: Session recording, dead letter queue, logs deletion will be handled by TTL
TABLES_TO_DELETE_TEAM_DATA_FROM = [
    "person",
    "person_distinct_id",
    "person_distinct_id2",
    "groups",
    "cohortpeople",
    "person_static_cohort",
    "plugin_log_entries",
]


def run_event_table_deletions():
    queued_event_deletions = AsyncDeletion.objects.filter(
        delete_verified_at__isnull=True, deletion_type__in=[DeletionType.Team, DeletionType.Person, DeletionType.Group]
    )
    process_found_event_table_deletions(list(queued_event_deletions))

    queued_cohortpeople_deletions = AsyncDeletion.objects.filter(
        delete_verified_at__isnull=True, deletion_type__in=[DeletionType.Cohort_full, DeletionType.Cohort_stale]
    )
    process_found_cohort_table_deletions(list(queued_cohortpeople_deletions))


def process_found_cohort_table_deletions(deletions: List[AsyncDeletion]):
    if len(deletions) == 0:
        logger.debug("No AsyncDeletion for cohorts to perform")
        return

    logger.info(
        "Starting AsyncDeletion on `cohortpeople` table in ClickHouse",
        {"count": len(deletions), "team_ids": list(set(row.team_id for row in deletions))},
    )

    conditions, args = _conditions(deletions)

    sync_execute(
        f"""
        ALTER TABLE cohortpeople
        DELETE WHERE {" OR ".join(conditions)}
        """,
        args,
    )


def process_found_event_table_deletions(deletions: List[AsyncDeletion]):
    if len(deletions) == 0:
        logger.debug("No AsyncDeletion to perform")
        return

    logger.info(
        "Starting AsyncDeletion on `events` table in ClickHouse",
        {"count": len(deletions), "team_ids": list(set(row.team_id for row in deletions))},
    )

    conditions, args = _conditions(deletions)
    sync_execute(
        f"""
        ALTER TABLE sharded_events
        ON CLUSTER '{CLICKHOUSE_CLUSTER}'
        DELETE WHERE {" OR ".join(conditions)}
        """,
        args,
    )

    # Team data needs to be deleted from other models as well, groups/persons handles deletions on a schema level
    team_deletions = [row for row in deletions if row.deletion_type == DeletionType.Team]

    if len(team_deletions) == 0:
        return

    logger.info(
        "Starting AsyncDeletion for teams on other tables",
        {"count": len(team_deletions), "team_ids": list(set(row.team_id for row in deletions))},
    )
    conditions, args = _conditions(team_deletions)
    for table in TABLES_TO_DELETE_TEAM_DATA_FROM:
        sync_execute(
            f"""
            ALTER TABLE {table}
            ON CLUSTER '{CLICKHOUSE_CLUSTER}'
            DELETE WHERE {" OR ".join(conditions)}
            """,
            args,
        )


def mark_deletions_done():
    """
    Checks and updates `delete_verified_at` for deletions
    """
    to_verify = []
    unverified = _fetch_unverified_deletions_grouped()

    for (deletion_type, _), async_deletions in unverified.items():
        to_verify.extend(_verify_by_group(deletion_type, async_deletions))

    if len(to_verify) > 0:
        AsyncDeletion.objects.filter(pk__in=[row.pk for row in to_verify]).update(delete_verified_at=timezone.now())
        logger.info(
            "Updated `delete_verified_at` for AsyncDeletion",
            {"count": len(to_verify), "team_ids": list(set(row.team_id for row in to_verify))},
        )


def _fetch_unverified_deletions_grouped():
    result = defaultdict(list)
    for item in AsyncDeletion.objects.filter(delete_verified_at__isnull=True):
        key = (item.deletion_type, item.group_type_index)
        result[key].append(item)
    return result


def _verify_by_group(deletion_type: int, async_deletions: List[AsyncDeletion]) -> List[AsyncDeletion]:
    if deletion_type == DeletionType.Team:
        team_ids_with_data = _verify_by_column("team_id", async_deletions)
        return [row for row in async_deletions if (row.team_id,) not in team_ids_with_data]
    elif deletion_type in (DeletionType.Person, DeletionType.Group):
        columns = f"team_id, {_column_name(async_deletions[0])}"
        with_data = set((team_id, str(key)) for team_id, key in _verify_by_column(columns, async_deletions))
        return [row for row in async_deletions if (row.team_id, row.key) not in with_data]
    else:
        return []


def _verify_by_column(distinct_columns: str, async_deletions: List[AsyncDeletion]) -> Set[Tuple[Any, ...]]:
    conditions, args = _conditions(async_deletions)
    clickhouse_result = sync_execute(
        f"""
        SELECT DISTINCT {distinct_columns}
        FROM events
        WHERE {" OR ".join(conditions)}
        """,
        args,
    )
    return set(tuple(row) for row in clickhouse_result)


def _column_name(async_deletion: AsyncDeletion):
    assert async_deletion.deletion_type in (
        DeletionType.Person,
        DeletionType.Group,
        DeletionType.Cohort_full,
        DeletionType.Cohort_stale,
    )
    if async_deletion.deletion_type == DeletionType.Person:
        return "person_id"
    elif (
        async_deletion.deletion_type == DeletionType.Cohort_full
        or async_deletion.deletion_type == DeletionType.Cohort_stale
    ):
        return "cohort_id"
    else:
        return f"$group_{async_deletion.group_type_index}"


def _conditions(async_deletions: List[AsyncDeletion]) -> Tuple[List[str], Dict]:
    conditions, args = [], {}
    for i, row in enumerate(async_deletions):
        condition, arg = _condition(row, str(i))
        conditions.append(condition)
        args.update(arg)
    return conditions, args


def _condition(async_deletion: AsyncDeletion, suffix: str) -> Tuple[str, Dict]:
    if async_deletion.deletion_type == DeletionType.Team:
        return f"team_id = %(team_id{suffix})s", {f"team_id{suffix}": async_deletion.team_id}
    elif async_deletion.deletion_type == DeletionType.Cohort_stale:
        key, version = async_deletion.key.split("_")
        return (
            f"team_id = %(team_id{suffix})s AND {_column_name(async_deletion)} = %(key{suffix})s AND version < %(version{suffix})s",
            {f"team_id{suffix}": async_deletion.team_id, f"version{suffix}": version, f"key{suffix}": key},
        )
    elif async_deletion.deletion_type == DeletionType.Cohort_full:
        key_version = async_deletion.key.split("_")
        key = key_version[0]
        return f"team_id = %(team_id{suffix})s AND {_column_name(async_deletion)} = %(key{suffix})s", {
            f"team_id{suffix}": async_deletion.team_id,
            f"key{suffix}": key,
        }
    else:
        return (
            f"(team_id = %(team_id{suffix})s AND {_column_name(async_deletion)} = %(key{suffix})s)",
            {f"team_id{suffix}": async_deletion.team_id, f"key{suffix}": async_deletion.key},
        )
