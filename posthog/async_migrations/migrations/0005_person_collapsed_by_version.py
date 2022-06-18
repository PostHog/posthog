import json
from functools import cached_property
from typing import Dict, List, Tuple

import structlog
from django.conf import settings
from django.utils.timezone import now

from posthog.async_migrations.definition import (
    AsyncMigrationDefinition,
    AsyncMigrationOperation,
    AsyncMigrationOperationSQL,
    AsyncMigrationType,
)
from posthog.async_migrations.utils import execute_op_clickhouse
from posthog.clickhouse.kafka_engine import STORAGE_POLICY
from posthog.clickhouse.table_engines import ReplacingMergeTree
from posthog.client import sync_execute
from posthog.constants import AnalyticsDBMS
from posthog.models.person.person import Person
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
    4. Backfill person rows from postgres
    5. Swap the tables

Constraints:
- Existing table will have a lot of rows with version = 0 - we need to re-copy them from postgres.
- Existing table will have rows with version out of sync with postgres - we need to re-copy them from postgres.
- We want to avoid data races. Hence we're turning on w.
- We can't use a second kafka consumer for the new table due to data integrity concerns, so we're leveraging
    multiple materialized views.
- Copying `persons` from postgres will be the slow part here and should be resumable. We leverage the fact
    person ids are monotonically increasing for this reason.
"""

REDIS_HIGHWATERMARK_KEY = "posthog.async_migrations.0005.highwatermark"

TEMPORARY_TABLE_NAME = f"{settings.CLICKHOUSE_DATABASE}.temp_events_0005_person_collapsed_by_version"
TEMPORARY_PERSON_MV = f"{settings.CLICKHOUSE_DATABASE}.tmp_person_mv_0005_person_collapsed_by_version"
PERSON_TABLE = "person"
PERSON_TABLE_NAME = f"{settings.CLICKHOUSE_DATABASE}.{PERSON_TABLE}"
BACKUP_TABLE_NAME = f"{PERSON_TABLE_NAME}_backup_0005_person_collapsed_by_version"
FAILED_PERSON_TABLE_NAME = f"{PERSON_TABLE_NAME}_failed_person_collapsed_by_version"

PG_COPY_BATCH_SIZE = 1000
PG_COPY_INSERT_TIMESTAMP = "2020-01-01 00:00:00.000000"

# :TODO: Move to an util
def optimize_table_fn(query_id):
    default_timeout = settings.ASYNC_MIGRATIONS_DEFAULT_TIMEOUT_SECONDS
    try:
        execute_op_clickhouse(
            f"OPTIMIZE TABLE {PERSON_TABLE} FINAL",
            query_id=query_id,
            settings={
                "max_execution_time": default_timeout,
                "send_timeout": default_timeout,
                "receive_timeout": default_timeout,
            },
        )
    except:  # TODO: we should only pass the timeout one here
        pass


class Migration(AsyncMigrationDefinition):
    description = "Move `person` table over to a improved schema from a correctness standpoint"

    depends_on = "0004_replicated_schema"

    def is_required(self) -> bool:
        person_table_engine = sync_execute(
            "SELECT engine_full FROM system.tables WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": "person"},
        )[0][0]

        return not ("ReplicatedReplacingMergeTree" in person_table_engine and ", version)" in person_table_engine)

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
                    FROM {settings.CLICKHOUSE_DATABASE}.kafka_persons
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
                rollback=f"TRUNCATE TABLE IF EXISTS {TEMPORARY_TABLE_NAME} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'",
                timeout_seconds=2 * 24 * 60 * 60,  # two days
            ),
            AsyncMigrationOperation(fn=self.copy_persons_from_postgres),
            # :TODO: recreate mv tables
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
            AsyncMigrationOperation(fn=optimize_table_fn),
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
        return Person.objects.latest("id").id

    def get_pg_copy_highwatermark(self) -> int:
        highwatermark = get_client().get(REDIS_HIGHWATERMARK_KEY)
        return highwatermark if highwatermark is not None else 0

    def copy_persons_from_postgres(self, query_id: str):
        should_continue = False
        while should_continue:
            should_continue = self._copy_batch_from_postgres(query_id)

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

    def _persons_insert_query(self, persons: List[Person]) -> Tuple[str, Dict]:
        values = []
        params = {}
        for i, person in enumerate(persons):
            # :TRICKY: We use a custom timestamp to identify these rows
            created_at = person.created_at.strftime("%Y-%m-%d %H:%M:%S.%f")
            values.append(
                f"('{person.uuid}', '{created_at}', {person.team_id}, %(properties_{i})s, {'1' if person.is_identified else '0'}, '{PG_COPY_INSERT_TIMESTAMP}', 0, 0, {person.version or 0})"
            )
            params[f"properties_{i}"] = json.dumps(person.properties)

        return (
            f"""
            INSERT INTO {TEMPORARY_TABLE_NAME} (
                id, created_at, team_id, properties, is_identified, _timestamp, _offset, is_deleted, version
            )
            VALUES {', '.join(values)}
            """,
            params,
        )

    def progress(self, migration_instance: AsyncMigrationType) -> int:
        # We weigh each step before copying persons as equal, and the persons copy as ~50% of progress
        result = 0.5 * migration_instance.current_operation_index / len(self.operations)

        if migration_instance.current_operation_index == 3:
            result += 0.5 * (self.get_pg_copy_highwatermark() / self.pg_copy_target_person_id)
        else:
            result += 0.5

        return int(100 * result)
