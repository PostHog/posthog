from typing import Any

from posthog.client import sync_execute
from posthog.models.async_deletion import AsyncDeletion, DeletionType, CLICKHOUSE_ASYNC_DELETION_TABLE
from posthog.models.async_deletion.delete import AsyncDeletionProcess, logger
from posthog.clickhouse.client.connection import Workload
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE
from posthog.clickhouse.client.escape import substitute_params

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
    DELETION_TYPES = [DeletionType.Team, DeletionType.Person]

    def process(self, deletions: list[AsyncDeletion]):
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
        temp_table_name = f"{CLICKHOUSE_DATABASE}.async_deletion_run"

        self._fill_table(deletions, temp_table_name)

        # joinGet is not an obvious function to wrap your head around, but in this case it's essentially
        # joinGet(async_deletion_run, [id, we're just looking for it to be non-zero], team_id, [deletion type], [key of the object to be deleted])
        #
        # the async_deletion_run table defines the keys you join on as (team_id, deletion_type, key)
        # you always have to pass all of the join keys to joinGet
        sync_execute(
            f"""
            ALTER TABLE sharded_events
            ON CLUSTER '{CLICKHOUSE_CLUSTER}'
            DELETE
            WHERE
                team_id IN %(team_ids)s AND
                (
                    joinGet({temp_table_name}, 'id', team_id, 0, toString(team_id)) > 0 OR
                    joinGet({temp_table_name}, 'id', team_id, 1, toString(person_id)) > 0
                )
            """,
            {"team_ids": team_ids},
            workload=Workload.OFFLINE,
        )

        # Team data needs to be deleted from other models as well, groups/persons handles deletions on a schema level
        team_deletions = [row for row in deletions if row.deletion_type == DeletionType.Team]

        if len(team_deletions) == 0:
            return

        logger.info(
            "Starting AsyncDeletion for teams on other tables",
            {
                "count": len(team_deletions),
                "team_ids": list({row.team_id for row in deletions}),
            },
        )
        for table in TABLES_TO_DELETE_TEAM_DATA_FROM:
            sync_execute(
                f"""
                ALTER TABLE {table}
                ON CLUSTER '{CLICKHOUSE_CLUSTER}'
                DELETE WHERE
                team_id IN %(team_ids)s AND
                joinGet({temp_table_name}, 'id', team_id, 0, toString(team_id)) > 0
                """,
                {"team_ids": [deletion.team_id for deletion in team_deletions]},
                workload=Workload.OFFLINE,
            )

    def _fill_table(self, deletions: list[AsyncDeletion], temp_table_name: str):
        sync_execute(f"DROP TABLE IF EXISTS {temp_table_name}", workload=Workload.OFFLINE)
        sync_execute(
            CLICKHOUSE_ASYNC_DELETION_TABLE.format(table_name=temp_table_name, cluster=CLICKHOUSE_CLUSTER),
            workload=Workload.OFFLINE,
        )

        for i in range(0, len(deletions), 1000):
            chunk = deletions[i : i + 1000]
            append = []
            for item in chunk:
                append.append(
                    substitute_params(
                        "(%(id)s, %(deletion_type)s, %(key)s, %(group_type_index)s, %(team_id)s)", item.__dict__
                    )
                )

            sync_execute(
                "INSERT INTO {} (id, deletion_type, key, group_type_index, team_id) VALUES {}".format(
                    temp_table_name, ",".join(append)
                ),
                workload=Workload.OFFLINE,
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
            workload=Workload.OFFLINE,
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
        else:
            return (
                f"(team_id = %(team_id{suffix})s AND {self._column_name(async_deletion)} = %(key{suffix})s)",
                {
                    f"team_id{suffix}": async_deletion.team_id,
                    f"key{suffix}": async_deletion.key,
                },
            )
