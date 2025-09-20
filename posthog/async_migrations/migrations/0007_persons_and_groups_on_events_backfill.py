from datetime import datetime
from functools import cached_property
from typing import Union

from django.conf import settings

import structlog

from posthog.async_migrations.definition import (
    AsyncMigrationDefinition,
    AsyncMigrationOperation,
    AsyncMigrationOperationSQL,
)
from posthog.async_migrations.disk_util import analyze_enough_disk_space_free_for_table
from posthog.async_migrations.utils import execute_op_clickhouse, run_optimize_table, sleep_until_finished
from posthog.clickhouse.client import sync_execute
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.utils import str_to_bool

logger = structlog.get_logger(__name__)


"""
Migration summary
=================

Backfill the sharded_events table to add data for the following columns:

- person_id
- person_properties
- person_created_at
- groupX_properties
- groupX_created_at

This allows us to switch entirely to only querying the events table for insights,
without having to hit additional tables for persons, groups, and distinct IDs.

Migration strategy
==================

We will run the following operations on the cluster
(or on one node per shard if shard-level configuration is provided):

1. Update `person_properties` and `groupX_properties` columns to use ZSTD(3) compression
2. Create temporary tables with the relevant columns from `person`, `person_distinct_id`, and `groups`
3. Copy data from the main tables into them
4. Optimize the temporary tables to remove duplicates and remove deleted data
5. Create a dictionary to query each temporary table with caching
6. Run an ALTER TABLE ... UPDATE to backfill all the data using the dictionaries

Constraints
===========

1. The migration requires a lot of extra space for the new columns. At least 2x disk space is required to avoid issues while migrating.
2. We use ZSTD(3) compression on the new columns to save on space and speed up large reads.
3. New columns need to be populated for new rows before running this async migration.
"""

TEMPORARY_PERSONS_TABLE_NAME = "tmp_person_0007"
TEMPORARY_PDI2_TABLE_NAME = "tmp_person_distinct_id2_0007"
TEMPORARY_GROUPS_TABLE_NAME = "tmp_groups_0007"

# :KLUDGE: On cloud, groups and person tables now have storage_policy sometimes attached
STORAGE_POLICY_SETTING = lambda: ", storage_policy = 'hot_to_cold'" if settings.CLICKHOUSE_ENABLE_STORAGE_POLICY else ""

# we shouldn't set this too low to avoid false positives for data inconsistency given we sample data
DEFAULT_ACCEPTED_INCONSISTENT_DATA_RATIO = 0.01


class Migration(AsyncMigrationDefinition):
    description = "Backfill persons and groups data on the sharded_events table"

    depends_on = "0006_persons_and_groups_on_events_backfill"

    posthog_min_version = "1.40.0"
    posthog_max_version = "1.41.99"

    parameters = {
        "PERSON_DICT_CACHE_SIZE": (
            5000000,
            "ClickHouse cache size (in rows) for persons data.",
            int,
        ),
        "PERSON_DISTINCT_ID_DICT_CACHE_SIZE": (
            5000000,
            "ClickHouse cache size (in rows) for person distinct id data.",
            int,
        ),
        "GROUPS_DICT_CACHE_SIZE": (
            1000000,
            "ClickHouse cache size (in rows) for groups data.",
            int,
        ),
        "RUN_DATA_VALIDATION_POSTCHECK": (
            "True",
            "Whether to run a postcheck validating the backfilled data.",
            str,
        ),
        "TIMESTAMP_LOWER_BOUND": (
            "2020-01-01",
            "Timestamp lower bound for events to backfill",
            str,
        ),
        "TIMESTAMP_UPPER_BOUND": (
            f"{datetime.now().year + 1}-01-01",
            "Timestamp upper bound for events to backfill",
            str,
        ),
        "TEAM_ID": (
            None,
            "The team_id of team to run backfill for. If unset the backfill will run for all teams.",
            int,
        ),
    }

    def precheck(self):
        return analyze_enough_disk_space_free_for_table(EVENTS_DATA_TABLE(), required_ratio=2.0)

    def is_required(self) -> bool:
        # we don't check groupX_created_at columns as they are 0 by default
        rows_to_backfill_check = sync_execute(
            """
            SELECT 1
            FROM events
            WHERE
                empty(person_id) OR
                person_created_at = toDateTime(0) OR
                person_properties = '' OR
                group0_properties = '' OR
                group1_properties = '' OR
                group2_properties = '' OR
                group3_properties = '' OR
                group4_properties = ''
            LIMIT 1
            """
        )

        return len(rows_to_backfill_check) > 0

    @cached_property
    def operations(self):
        return [
            AsyncMigrationOperation(
                # See https://github.com/PostHog/posthog/issues/10616 for details on choice of codec
                fn=lambda query_id: self._update_properties_column_compression_codec(query_id, "ZSTD(3)"),
                rollback_fn=lambda query_id: self._update_properties_column_compression_codec(query_id, "LZ4"),
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    CREATE TABLE {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}}
                    AS {settings.CLICKHOUSE_DATABASE}.person
                    ENGINE = ReplacingMergeTree(version)
                    ORDER BY (team_id, id)
                    SETTINGS index_granularity = 128 {STORAGE_POLICY_SETTING()}
                """,
                rollback=f"DROP TABLE IF EXISTS {TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}}",
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    CREATE TABLE {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}}
                    AS {settings.CLICKHOUSE_DATABASE}.person_distinct_id2
                    ENGINE = ReplacingMergeTree(version)
                    ORDER BY (team_id, distinct_id)
                    SETTINGS index_granularity = 128
                """,
                rollback=f"DROP TABLE IF EXISTS {TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}}",
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    CREATE TABLE {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_GROUPS_TABLE_NAME} {{on_cluster_clause}}
                    AS {settings.CLICKHOUSE_DATABASE}.groups
                    ENGINE = ReplacingMergeTree(_timestamp)
                    ORDER BY (team_id, group_type_index, group_key)
                    SETTINGS index_granularity = 128 {STORAGE_POLICY_SETTING()}
                """,
                rollback=f"DROP TABLE IF EXISTS {TEMPORARY_GROUPS_TABLE_NAME} {{on_cluster_clause}}",
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}}
                    REPLACE PARTITION tuple() FROM {settings.CLICKHOUSE_DATABASE}.person
                """,
                rollback=None,
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}}
                    REPLACE PARTITION tuple() FROM {settings.CLICKHOUSE_DATABASE}.person_distinct_id2
                """,
                rollback=None,
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_GROUPS_TABLE_NAME} {{on_cluster_clause}}
                    REPLACE PARTITION tuple() FROM {settings.CLICKHOUSE_DATABASE}.groups
                """,
                rollback=None,
                per_shard=True,
            ),
            AsyncMigrationOperation(
                fn=lambda query_id: run_optimize_table(
                    unique_name="0007_persons_and_groups_on_events_backfill_person",
                    query_id=query_id,
                    table_name=f"{settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PERSONS_TABLE_NAME}",
                    final=True,
                    deduplicate=True,
                    per_shard=True,
                )
            ),
            AsyncMigrationOperation(
                fn=lambda query_id: run_optimize_table(
                    unique_name="0007_persons_and_groups_on_events_backfill_pdi2",
                    query_id=query_id,
                    table_name=f"{settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PDI2_TABLE_NAME}",
                    final=True,
                    deduplicate=True,
                    per_shard=True,
                )
            ),
            AsyncMigrationOperation(
                fn=lambda query_id: run_optimize_table(
                    unique_name="0007_persons_and_groups_on_events_backfill_groups",
                    query_id=query_id,
                    table_name=f"{settings.CLICKHOUSE_DATABASE}.{TEMPORARY_GROUPS_TABLE_NAME}",
                    final=True,
                    deduplicate=True,
                    per_shard=True,
                )
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}}
                    DELETE WHERE is_deleted = 1 OR person_id IN (
                        SELECT id FROM {TEMPORARY_PERSONS_TABLE_NAME} WHERE is_deleted=1
                    )
                """,
                sql_settings={"mutations_sync": 2},
                rollback=None,
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}}
                    DELETE WHERE is_deleted = 1
                """,
                sql_settings={"mutations_sync": 2},
                rollback=None,
                per_shard=True,
            ),
            AsyncMigrationOperation(fn=self._create_dictionaries, rollback_fn=self._clear_temporary_tables),
            AsyncMigrationOperation(fn=self._run_backfill_mutation),
            AsyncMigrationOperation(fn=self._wait_for_mutation_done),
            AsyncMigrationOperation(fn=lambda query_id: self._postcheck(query_id)),
            AsyncMigrationOperation(fn=self._clear_temporary_tables),
        ]

    def _dictionary_connection_string(self):
        result = f"DB '{settings.CLICKHOUSE_DATABASE}'"
        if settings.CLICKHOUSE_USER:
            result += f" USER '{settings.CLICKHOUSE_USER}'"
        if settings.CLICKHOUSE_PASSWORD:
            result += f" PASSWORD '{settings.CLICKHOUSE_PASSWORD}'"
        return result

    def _update_properties_column_compression_codec(self, query_id, codec):
        columns = [
            "person_properties",
            "group0_properties",
            "group1_properties",
            "group2_properties",
            "group3_properties",
            "group4_properties",
        ]
        for column in columns:
            execute_op_clickhouse(
                query_id=query_id,
                sql=f"ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{EVENTS_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' MODIFY COLUMN {column} VARCHAR Codec({codec})",
            )

    def _postcheck(self, _: str):
        if str_to_bool(self.get_parameter("RUN_DATA_VALIDATION_POSTCHECK")):
            self._check_person_data()
            self._check_groups_data()

    def _where_clause(self) -> tuple[str, dict[str, Union[str, int]]]:
        team_id = self.get_parameter("TEAM_ID")
        team_id_filter = f" AND team_id = %(team_id)s" if team_id else ""
        where_clause = f"WHERE timestamp > toDateTime(%(timestamp_lower_bound)s) AND timestamp < toDateTime(%(timestamp_upper_bound)s) {team_id_filter}"

        return (
            where_clause,
            {
                "team_id": team_id,
                "timestamp_lower_bound": self.get_parameter("TIMESTAMP_LOWER_BOUND"),
                "timestamp_upper_bound": self.get_parameter("TIMESTAMP_UPPER_BOUND"),
            },
        )

    def _check_person_data(self, threshold=DEFAULT_ACCEPTED_INCONSISTENT_DATA_RATIO):
        where_clause, where_clause_params = self._where_clause()

        incomplete_person_data_ratio = sync_execute(
            f"""
            SELECT countIf(
                empty(person_id) OR
                person_created_at = toDateTime(0) OR
                person_properties = ''
            ) / count() FROM events
            SAMPLE 10000000
            {where_clause}
            """,
            where_clause_params,
        )[0][0]

        if incomplete_person_data_ratio > threshold:
            incomplete_events_percentage = incomplete_person_data_ratio * 100
            raise Exception(
                f"Backfill did not work succesfully. ~{int(incomplete_events_percentage)}% of events did not get the correct data for persons."
            )

    def _check_groups_data(self, threshold=DEFAULT_ACCEPTED_INCONSISTENT_DATA_RATIO):
        where_clause, where_clause_params = self._where_clause()

        # To check if groups data was not backfilled, we check for:
        # 1. groupX_properties = '' (because the backfill sets group properties to '{}' if the group doesn't exist)
        # 2. groupX_created_at != created_at column of groups table via dictionary lookup (because we can't just look for groups with toDateTime(0) as that's the default)
        incomplete_groups_data_ratio = sync_execute(
            f"""
            SELECT countIf(
                group0_properties = '' OR
                group0_created_at != dictGetDateTime('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'created_at', tuple(team_id, 0, $group_0)) OR
                group1_properties = '' OR
                group1_created_at != dictGetDateTime('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'created_at', tuple(team_id, 1, $group_1)) OR
                group2_properties = '' OR
                group2_created_at != dictGetDateTime('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'created_at', tuple(team_id, 2, $group_2)) OR
                group3_properties = '' OR
                group3_created_at != dictGetDateTime('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'created_at', tuple(team_id, 3, $group_3)) OR
                group4_properties = '' OR
                group4_created_at != dictGetDateTime('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'created_at', tuple(team_id, 4, $group_4))
            ) / count() FROM events
            SAMPLE 10000000
            {where_clause}
            """,
            where_clause_params,
        )[0][0]

        if incomplete_groups_data_ratio > threshold:
            incomplete_events_percentage = incomplete_groups_data_ratio * 100
            raise Exception(
                f"Backfill did not work succesfully. ~{int(incomplete_events_percentage)}% of events did not get the correct data for groups."
            )

    def _run_backfill_mutation(self, query_id):
        # If there's an ongoing backfill, skip enqueuing another and jump to the step where we wait for the mutation to finish
        if self._count_running_mutations() > 0:
            return

        where_clause, where_clause_params = self._where_clause()

        execute_op_clickhouse(
            f"""
                ALTER TABLE {EVENTS_DATA_TABLE()}
                {{on_cluster_clause}}
                UPDATE
                    person_id = if(
                        empty(person_id),
                        toUUID(dictGet('{settings.CLICKHOUSE_DATABASE}.person_distinct_id2_dict', 'person_id', tuple(team_id, distinct_id))),
                        person_id
                    ),
                    person_properties = if(
                        person_properties = '',
                        dictGetStringOrDefault(
                            '{settings.CLICKHOUSE_DATABASE}.person_dict',
                            'properties',
                            tuple(
                                team_id,
                                toUUID(dictGet('{settings.CLICKHOUSE_DATABASE}.person_distinct_id2_dict', 'person_id', tuple(team_id, distinct_id)))
                            ),
                            toJSONString(map())
                        ),
                        person_properties
                    ),
                    person_created_at = if(
                        person_created_at = toDateTime(0),
                        dictGetDateTime(
                            '{settings.CLICKHOUSE_DATABASE}.person_dict',
                            'created_at',
                            tuple(
                                team_id,
                                toUUID(dictGet('{settings.CLICKHOUSE_DATABASE}.person_distinct_id2_dict', 'person_id', tuple(team_id, distinct_id)))
                            )
                        ),
                        person_created_at
                    ),
                    group0_properties = if(
                        group0_properties = '',
                        dictGetStringOrDefault('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'group_properties', tuple(team_id, 0, $group_0), toJSONString(map())),
                        group0_properties
                    ),
                    group1_properties = if(
                        group1_properties = '',
                        dictGetStringOrDefault('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'group_properties', tuple(team_id, 1, $group_1), toJSONString(map())),
                        group1_properties
                    ),
                    group2_properties = if(
                        group2_properties = '',
                        dictGetStringOrDefault('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'group_properties', tuple(team_id, 2, $group_2), toJSONString(map())),
                        group2_properties
                    ),
                    group3_properties = if(
                        group3_properties = '',
                        dictGetStringOrDefault('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'group_properties', tuple(team_id, 3, $group_3), toJSONString(map())),
                        group3_properties
                    ),
                    group4_properties = if(
                        group4_properties = '',
                        dictGetStringOrDefault('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'group_properties', tuple(team_id, 4, $group_4), toJSONString(map())),
                        group4_properties
                    ),
                    group0_created_at = if(
                        group0_created_at = toDateTime(0),
                        dictGetDateTime('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'created_at', tuple(team_id, 0, $group_0)),
                        group0_created_at
                    ),
                    group1_created_at = if(
                        group1_created_at = toDateTime(0),
                        dictGetDateTime('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'created_at', tuple(team_id, 1, $group_1)),
                        group1_created_at
                    ),
                    group2_created_at = if(
                        group2_created_at = toDateTime(0),
                        dictGetDateTime('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'created_at', tuple(team_id, 2, $group_2)),
                        group2_created_at
                    ),
                    group3_created_at = if(
                        group3_created_at = toDateTime(0),
                        dictGetDateTime('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'created_at', tuple(team_id, 3, $group_3)),
                        group3_created_at
                    ),
                    group4_created_at = if(
                        group4_created_at = toDateTime(0),
                        dictGetDateTime('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'created_at', tuple(team_id, 4, $group_4)),
                        group4_created_at
                    )
                {where_clause}
            """,
            where_clause_params,
            settings={"max_execution_time": 0},
            per_shard=True,
            query_id=query_id,
        )

    def _create_dictionaries(self, query_id):
        (
            execute_op_clickhouse(
                f"""
                CREATE DICTIONARY IF NOT EXISTS {settings.CLICKHOUSE_DATABASE}.person_dict {{on_cluster_clause}}
                (
                    team_id Int64,
                    id UUID,
                    properties String,
                    created_at DateTime
                )
                PRIMARY KEY team_id, id
                SOURCE(CLICKHOUSE(TABLE {TEMPORARY_PERSONS_TABLE_NAME} {self._dictionary_connection_string()}))
                LAYOUT(complex_key_cache(size_in_cells %(cache_size)s max_threads_for_updates 6 allow_read_expired_keys 1))
                Lifetime(60000)
            """,
                {"cache_size": self.get_parameter("PERSON_DICT_CACHE_SIZE")},
                per_shard=True,
                query_id=query_id,
            ),
        )
        (
            execute_op_clickhouse(
                f"""
                CREATE DICTIONARY IF NOT EXISTS {settings.CLICKHOUSE_DATABASE}.person_distinct_id2_dict {{on_cluster_clause}}
                (
                    team_id Int64,
                    distinct_id String,
                    person_id UUID
                )
                PRIMARY KEY team_id, distinct_id
                SOURCE(CLICKHOUSE(TABLE {TEMPORARY_PDI2_TABLE_NAME} {self._dictionary_connection_string()}))
                LAYOUT(complex_key_cache(size_in_cells %(cache_size)s max_threads_for_updates 6 allow_read_expired_keys 1))
                Lifetime(60000)
            """,
                {"cache_size": self.get_parameter("PERSON_DISTINCT_ID_DICT_CACHE_SIZE")},
                per_shard=True,
                query_id=query_id,
            ),
        )
        execute_op_clickhouse(
            f"""
                CREATE DICTIONARY IF NOT EXISTS {settings.CLICKHOUSE_DATABASE}.groups_dict {{on_cluster_clause}}
                (
                    team_id Int64,
                    group_type_index UInt8,
                    group_key String,
                    group_properties String,
                    created_at DateTime
                )
                PRIMARY KEY team_id, group_type_index, group_key
                SOURCE(CLICKHOUSE(TABLE {TEMPORARY_GROUPS_TABLE_NAME} {self._dictionary_connection_string()}))
                LAYOUT(complex_key_cache(size_in_cells %(cache_size)s max_threads_for_updates 6 allow_read_expired_keys 1))
                Lifetime(60000)
            """,
            {"cache_size": self.get_parameter("GROUPS_DICT_CACHE_SIZE")},
            per_shard=True,
            query_id=query_id,
        )

    def _wait_for_mutation_done(self, query_id):
        # :KLUDGE: mutations_sync does not work with ON CLUSTER queries, causing race conditions with subsequent steps
        sleep_until_finished("events table backill", lambda: self._count_running_mutations() > 0)

    def _count_running_mutations(self):
        return sync_execute(
            """
            SELECT count()
            FROM clusterAllReplicas(%(cluster)s, system, 'mutations')
            WHERE not is_done AND command LIKE %(pattern)s
            """,
            {
                "cluster": settings.CLICKHOUSE_CLUSTER,
                "pattern": "%person_created_at = toDateTime(0)%",
            },
        )[0][0]

    def _clear_temporary_tables(self, query_id):
        queries = [
            f"DROP DICTIONARY IF EXISTS {settings.CLICKHOUSE_DATABASE}.person_dict {{on_cluster_clause}}",
            f"DROP DICTIONARY IF EXISTS {settings.CLICKHOUSE_DATABASE}.person_distinct_id2_dict {{on_cluster_clause}}",
            f"DROP DICTIONARY IF EXISTS {settings.CLICKHOUSE_DATABASE}.groups_dict {{on_cluster_clause}}",
            f"DROP TABLE IF EXISTS {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}}",
            f"DROP TABLE IF EXISTS {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}}",
            f"DROP TABLE IF EXISTS {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_GROUPS_TABLE_NAME} {{on_cluster_clause}}",
        ]
        for query in queries:
            execute_op_clickhouse(query_id=query_id, sql=query, per_shard=True)

    def healthcheck(self):
        result = sync_execute("SELECT free_space FROM system.disks")
        # 100mb or less left
        if int(result[0][0]) < 100000000:
            return (False, "ClickHouse available storage below 100MB")

        return (True, None)
