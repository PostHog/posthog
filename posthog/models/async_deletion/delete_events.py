from typing import Any

from prometheus_client import Counter

from posthog.client import sync_execute
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.async_deletion.delete import AsyncDeletionProcess, logger
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER


deletions_counter = Counter("deletions_executed", "Total number of deletions sent to clickhouse", ["deletion_type"])


MAX_PREDICATE_SIZE = 240_000  # 240KB

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


class AsyncEventDeletion(AsyncDeletionProcess):
    DELETION_TYPES = [DeletionType.Team, DeletionType.Group, DeletionType.Person]

    def process(self, deletions: list[AsyncDeletion]):
        deletions_counter.labels(deletion_type="event").inc(len(deletions))

        if len(deletions) == 0:
            logger.debug("No AsyncDeletion to perform")
            return

        team_ids = list({row.team_id for row in deletions})

        logger.info(
            "Starting AsyncDeletion on `events` table in ClickHouse",
            {
                "count": len(deletions),
                "team_ids": team_ids,
            },
        )

        conditions, args = self._conditions(deletions)

        # Split the deletions into chunks to avoid hitting the max query size
        query_predicate = []
        for condition in conditions:
            query_predicate.append(condition)

            # Get estimated  byte size of the query
            str_predicate = " OR ".join(query_predicate)
            query_size = len(str_predicate.encode("utf-8"))

            # If the query size is greater than the max predicate size, execute the query and reset the query predicate
            if query_size > MAX_PREDICATE_SIZE:
                next_args, rest_args = split_dict(args, len(query_predicate) - 1)
                sync_execute(
                    f"""
                    DELETE FROM posthog.sharded_events
                    ON CLUSTER '{CLICKHOUSE_CLUSTER}'
                    WHERE {str_predicate}
                    """,
                    next_args,
                    settings={},
                )
                # Reset the query predicate and predicate args
                args = rest_args
                query_predicate = []

        # This is the default condition if we don't hit the MAX_PREDICATE_SIZE
        sync_execute(
            f"""
            DELETE FROM sharded_events
            ON CLUSTER '{CLICKHOUSE_CLUSTER}'
            WHERE {str_predicate}
            """,
            args,
            settings={},
        )

        # Team data needs to be deleted from other models as well, groups/persons handles deletions on a schema level
        team_deletions = [row for row in deletions if row.deletion_type == DeletionType.Team]

        deletions_counter.labels(deletion_type=DeletionType.Team).inc(len(team_deletions))
        if len(team_deletions) == 0:
            return

        logger.info(
            "Starting AsyncDeletion for teams on other tables",
            {
                "count": len(team_deletions),
                "team_ids": list({row.team_id for row in deletions}),
            },
        )
        conditions, args = self._conditions(team_deletions)
        for table in TABLES_TO_DELETE_TEAM_DATA_FROM:
            sync_execute(
                f"""
                DELETE FROM {table}
                ON CLUSTER '{CLICKHOUSE_CLUSTER}'
                WHERE {" OR ".join(conditions)}
                """,
                args,
                settings={},
            )

    def _verify_by_group(self, deletion_type: int, async_deletions: list[AsyncDeletion]) -> list[AsyncDeletion]:
        if deletion_type == DeletionType.Team:
            team_ids_with_data = self._verify_by_column("team_id", async_deletions)
            return [row for row in async_deletions if (row.team_id,) not in team_ids_with_data]
        elif deletion_type in (DeletionType.Person, DeletionType.Group):
            columns = f"team_id, {self._column_name(async_deletions[0])}"
            with_data = {(team_id, str(key)) for team_id, key in self._verify_by_column(columns, async_deletions)}
            return [row for row in async_deletions if (row.team_id, row.key) not in with_data]
        else:
            return []

    def _verify_by_column(self, distinct_columns: str, async_deletions: list[AsyncDeletion]) -> set[tuple[Any, ...]]:
        conditions, args = self._conditions(async_deletions)
        clickhouse_result = sync_execute(
            f"""
            SELECT DISTINCT {distinct_columns}
            FROM events
            WHERE {" OR ".join(conditions)}
            """,
            args,
            settings={"max_execution_time": 30 * 60},
        )
        return {tuple(row) for row in clickhouse_result}

    def _column_name(self, async_deletion: AsyncDeletion):
        assert async_deletion.deletion_type in (DeletionType.Person, DeletionType.Group)
        if async_deletion.deletion_type == DeletionType.Person:
            return "person_id"
        else:
            return f"$group_{async_deletion.group_type_index}"

    def _condition(self, async_deletion: AsyncDeletion, suffix: str) -> tuple[str, dict]:
        if async_deletion.deletion_type == DeletionType.Team:
            return f"team_id = %(team_id{suffix})s", {f"team_id{suffix}": async_deletion.team_id}
        elif async_deletion.deletion_type == DeletionType.Person:
            # `person_id` is deterministic, meaning it can be reused after a user marks the person
            # for deletion. For that reason we only delete events that happened up to the point when
            # the delete was requested.
            return (
                f"(team_id = %(team_id{suffix})s AND {self._column_name(async_deletion)} = %(key{suffix})s) AND _timestamp <= %(timestamp{suffix})s",
                {
                    f"team_id{suffix}": async_deletion.team_id,
                    f"key{suffix}": async_deletion.key,
                    f"timestamp{suffix}": async_deletion.created_at,
                },
            )
        else:
            return (
                f"(team_id = %(team_id{suffix})s AND {self._column_name(async_deletion)} = %(key{suffix})s)",
                {
                    f"team_id{suffix}": async_deletion.team_id,
                    f"key{suffix}": async_deletion.key,
                },
            )


def split_dict(original_dict, n):
    items = list(original_dict.items())

    # Split the items
    first_n = dict(items[:n])
    rest = dict(items[n:])

    return first_n, rest
