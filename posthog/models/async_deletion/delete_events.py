from typing import Any

from clickhouse_driver.errors import SocketTimeoutError
from prometheus_client import Counter

from posthog.clickhouse.client import sync_execute
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.async_deletion.delete import AsyncDeletionProcess, logger
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER

logger.setLevel("DEBUG")

deletions_counter = Counter("deletions_executed", "Total number of deletions sent to clickhouse", ["deletion_type"])

# We purposely set this lower than the 256KB limit in ClickHouse to account for the potential overhead of the argument
# substitution and settings injection. This is a conservative estimate, but it's better to be safe than hit the limit.
MAX_QUERY_SIZE = 230_000  # 230KB which is less than 256KB limit in ClickHouse
MAX_SELECT_EXECUTION_TIME = 1 * 60 * 60  # 1 hour(s)


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

        conditions, args = [], {}
        for i, deletion in enumerate(deletions):
            condition, arg = self._condition(deletion, str(i))

            conditions.append(condition)
            args.update(arg)

            # Get estimated  byte size of the query
            str_predicate = " OR ".join(conditions)
            query = f"DELETE FROM sharded_events ON CLUSTER '{CLICKHOUSE_CLUSTER}' WHERE {str_predicate}"
            query_size = len(query.encode("utf-8"))

            logger.debug(f"Query size: {query_size}")
            logger.debug(f"Query: {query}")
            logger.debug(f"Query deletions: {deletions}")

            # If the query size is greater than the max predicate size, execute the query and reset the query predicate
            if query_size > MAX_QUERY_SIZE:
                logger.debug(f"Executing query with args: {args}")
                try:
                    sync_execute(
                        query,
                        args,
                        settings={},
                    )
                except SocketTimeoutError:
                    # This is unfortunately needed because currently all lightweight deletes are executed sync
                    logger.warning(
                        "ClickHouse query timed out during async deletion. This is expected. Continuing with next batch.",
                        exc_info=True,
                    )

                conditions, args = [], {}

        logger.debug(f"Executing query with args: {args}")

        # This is the default condition if we don't hit the MAX_QUERY_SIZE
        sync_execute(
            query,
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
            query = f"""DELETE FROM {table} ON CLUSTER '{CLICKHOUSE_CLUSTER}' WHERE {" OR ".join(conditions)}"""
            sync_execute(
                query,
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
            settings={"max_execution_time": MAX_SELECT_EXECUTION_TIME},
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
