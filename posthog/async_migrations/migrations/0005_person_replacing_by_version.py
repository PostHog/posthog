import json
from functools import cached_property

from django.conf import settings
from django.utils.timezone import now

import structlog

from posthog.async_migrations.definition import (
    AsyncMigrationDefinition,
    AsyncMigrationOperation,
    AsyncMigrationOperationSQL,
)
from posthog.async_migrations.utils import execute_op_clickhouse, run_optimize_table
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.kafka_engine import STORAGE_POLICY
from posthog.clickhouse.table_engines import ReplacingMergeTree
from posthog.constants import AnalyticsDBMS
from posthog.exceptions_capture import capture_exception
from posthog.models.async_migration import AsyncMigration
from posthog.models.person.person import Person
from posthog.models.person.sql import PERSONS_TABLE_MV_SQL
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

"""
Migration summary:

Use `version` column instead of `_timestamp` for collapsing persons table.

Using `_timestamp` makes us vulnerable to data integrity issues due to race conditions and
batching of kafka messages within plugin-server.

The migration strategy:

    1. We create a new table with the appropriate schema
    2. Ingest both in there and into old table
    3. Copy data over from original `persons` table.
    4. Swap the tables
    5. Try backfill person rows from postgres

Constraints:
- Existing table will have a lot of rows with version = 0 - we need to re-copy them from postgres.
- Existing table will have rows with version out of sync with postgres - we need to re-copy them from postgres.
- We want to avoid data races. Hence we're turning on writes before copying data from old table or postgres.
- We can't use a second kafka consumer for the new table due to data integrity concerns, so we're leveraging
    multiple materialized views.
- Copying `persons` from postgres will be the slow part here and should be resumable. We leverage the fact
    person ids are monotonically increasing for this reason.
- If backfilling from postgres fails, we only log the error - it's not operationally catastrophic and no reason to
    roll everything back.
"""

REDIS_HIGHWATERMARK_KEY = "posthog.async_migrations.0005.highwatermark"

TEMPORARY_TABLE_NAME = f"{settings.CLICKHOUSE_DATABASE}.tmp_person_0005_person_replacing_by_version"
TEMPORARY_PERSON_MV = f"{settings.CLICKHOUSE_DATABASE}.tmp_person_mv_0005_person_replacing_by_version"
PERSON_TABLE = "person"
PERSON_TABLE_NAME = f"{settings.CLICKHOUSE_DATABASE}.{PERSON_TABLE}"
BACKUP_TABLE_NAME = f"{PERSON_TABLE_NAME}_backup_0005_person_replacing_by_version"
FAILED_PERSON_TABLE_NAME = f"{PERSON_TABLE_NAME}_failed_0005_person_replacing_by_version"

PG_COPY_BATCH_SIZE = 1000
PG_COPY_INSERT_TIMESTAMP = "2020-01-01 00:00:00"


class Migration(AsyncMigrationDefinition):
    description = "Move `person` table over to a improved schema from a correctness standpoint"

    depends_on = "0004_replicated_schema"

    posthog_min_version = "1.38.0"
    posthog_max_version = "1.41.99"

    def is_required(self) -> bool:
        person_table_engine = sync_execute(
            "SELECT engine_full FROM system.tables WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": "person"},
        )[0][0]

        has_new_engine = "ReplicatedReplacingMergeTree" in person_table_engine and ", version)" in person_table_engine
        persons_backfill_ongoing = get_client().get(REDIS_HIGHWATERMARK_KEY) is not None
        return not has_new_engine or persons_backfill_ongoing

    @cached_property
    def operations(self):
        return [
            AsyncMigrationOperationSQL(
                database=AnalyticsDBMS.CLICKHOUSE,
                sql=f"""
                    CREATE TABLE IF NOT EXISTS {TEMPORARY_TABLE_NAME} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' AS {PERSON_TABLE_NAME}
                    ENGINE = {self.new_table_engine()}
                    ORDER BY (team_id, id)
                    {STORAGE_POLICY()}
                """,
                rollback=f"DROP TABLE IF EXISTS {TEMPORARY_TABLE_NAME} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'",
            ),
            AsyncMigrationOperationSQL(
                database=AnalyticsDBMS.CLICKHOUSE,
                sql=f"""
                    CREATE MATERIALIZED VIEW {TEMPORARY_PERSON_MV} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
                    TO {TEMPORARY_TABLE_NAME}
                    AS SELECT
                        id,
                        created_at,
                        team_id,
                        properties,
                        is_identified,
                        is_deleted,
                        version,
                        _timestamp,
                        _offset
                    FROM {settings.CLICKHOUSE_DATABASE}.kafka_person
                """,
                rollback=f"DROP TABLE IF EXISTS {TEMPORARY_PERSON_MV} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'",
            ),
            AsyncMigrationOperationSQL(
                database=AnalyticsDBMS.CLICKHOUSE,
                sql=f"""
                    INSERT INTO {TEMPORARY_TABLE_NAME}
                    SELECT *
                    FROM {PERSON_TABLE}
                """,
                # This speeds up copying significantly
                sql_settings={
                    "max_block_size": 50000,
                    "max_insert_block_size": 50000,
                    "max_threads": 20,
                    "max_insert_threads": 20,
                    "optimize_on_insert": 0,
                    "max_execution_time": 2 * 24 * 60 * 60,  # two days
                    "send_timeout": 2 * 24 * 60 * 60,  # two days,
                    "receive_timeout": 2 * 24 * 60 * 60,  # two days,
                },
                rollback=f"TRUNCATE TABLE IF EXISTS {TEMPORARY_TABLE_NAME} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'",
            ),
            AsyncMigrationOperationSQL(
                database=AnalyticsDBMS.CLICKHOUSE,
                sql=f"DROP TABLE IF EXISTS {TEMPORARY_PERSON_MV} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'",
                rollback=None,
            ),
            AsyncMigrationOperationSQL(
                database=AnalyticsDBMS.CLICKHOUSE,
                sql=f"DROP TABLE IF EXISTS person_mv ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'",
                rollback=None,
            ),
            AsyncMigrationOperationSQL(
                database=AnalyticsDBMS.CLICKHOUSE,
                sql=f"""
                    RENAME TABLE
                        {PERSON_TABLE_NAME} to {BACKUP_TABLE_NAME},
                        {TEMPORARY_TABLE_NAME} to {PERSON_TABLE_NAME}
                    ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
                """,
                rollback=f"""
                    RENAME TABLE
                        {PERSON_TABLE_NAME} to {FAILED_PERSON_TABLE_NAME},
                        {BACKUP_TABLE_NAME} to {PERSON_TABLE_NAME}
                    ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
                """,
            ),
            AsyncMigrationOperationSQL(
                database=AnalyticsDBMS.CLICKHOUSE,
                sql=PERSONS_TABLE_MV_SQL(target_table=PERSON_TABLE),
                rollback=None,
            ),
            AsyncMigrationOperation(
                fn=self.copy_persons_from_postgres,
                rollback_fn=lambda _: self.unset_highwatermark(),
            ),
        ]

    def new_table_engine(self):
        engine = ReplacingMergeTree("person", ver="version")
        # :TRICKY: Zookeeper paths need to be unique each time we run this migration, so generate a unique prefix.
        engine.set_zookeeper_path_key(now().strftime("am0005_%Y%m%d%H%M%S"))
        return engine

    @cached_property
    def pg_copy_target_person_id(self) -> int:
        # :TRICKY: We calculate the last ID to copy at the start of migration once and cache it.
        #    If the migration gets e.g. restarted, this is recalculated.
        try:
            return Person.objects.latest("id").id
        except Person.DoesNotExist:
            return -1

    def get_pg_copy_highwatermark(self) -> int:
        highwatermark = get_client().get(REDIS_HIGHWATERMARK_KEY)
        return int(highwatermark) if highwatermark is not None else 0

    def unset_highwatermark(self) -> None:
        get_client().delete(REDIS_HIGHWATERMARK_KEY)

    def copy_persons_from_postgres(self, query_id: str):
        try:
            should_continue = True
            while should_continue:
                should_continue = self._copy_batch_from_postgres(query_id)
            self.unset_highwatermark()
            run_optimize_table(
                unique_name="0005_person_replacing_by_version",
                query_id=query_id,
                table_name=PERSON_TABLE,
                final=True,
            )
        except Exception as err:
            logger.warn(
                "Re-copying persons from postgres failed. Marking async migration as complete.",
                error=err,
            )
            capture_exception(err)

    def _copy_batch_from_postgres(self, query_id: str) -> bool:
        highwatermark = self.get_pg_copy_highwatermark()
        if highwatermark > self.pg_copy_target_person_id:
            logger.info(
                "Finished copying people from postgres to clickhouse",
                highwatermark=highwatermark,
                pg_copy_target_person_id=self.pg_copy_target_person_id,
            )
            return False

        persons = list(Person.objects.filter(id__gte=highwatermark)[:PG_COPY_BATCH_SIZE])
        sql, params = self._persons_insert_query(persons)

        execute_op_clickhouse(sql, params, query_id=query_id)

        new_highwatermark = (persons[-1].id if len(persons) > 0 else self.pg_copy_target_person_id) + 1
        get_client().set(REDIS_HIGHWATERMARK_KEY, new_highwatermark)
        logger.debug(
            "Copied batch of people from postgres to clickhouse",
            batch_size=len(persons),
            previous_highwatermark=highwatermark,
            new_highwatermark=new_highwatermark,
            pg_copy_target_person_id=self.pg_copy_target_person_id,
        )
        return True

    def _persons_insert_query(self, persons: list[Person]) -> tuple[str, dict]:
        values = []
        params: dict = {}
        for i, person in enumerate(persons):
            created_at = person.created_at.strftime("%Y-%m-%d %H:%M:%S")
            # :TRICKY: We use a custom _timestamp to identify rows migrated during this migration
            values.append(
                f"(%(uuid_{i})s, '{created_at}', {person.team_id}, %(properties_{i})s, {'1' if person.is_identified else '0'}, '{PG_COPY_INSERT_TIMESTAMP}', 0, 0, {person.version or 0})"
            )
            params[f"uuid_{i}"] = str(person.uuid)
            params[f"properties_{i}"] = json.dumps(person.properties)

        return (
            f"""
            INSERT INTO {PERSON_TABLE_NAME} (
                id, created_at, team_id, properties, is_identified, _timestamp, _offset, is_deleted, version
            )
            VALUES {", ".join(values)}
            """,
            params,
        )

    def progress(self, migration_instance: AsyncMigration) -> int:
        # We weigh each step before copying persons as equal, and the persons copy as ~50% of progress
        result = 0.5 * migration_instance.current_operation_index / len(self.operations)

        if migration_instance.current_operation_index == len(self.operations) - 1:
            result = 0.5 + 0.5 * (self.get_pg_copy_highwatermark() / self.pg_copy_target_person_id)
        else:
            result = 0.5 * migration_instance.current_operation_index / (len(self.operations) - 1)

        return int(100 * result)
