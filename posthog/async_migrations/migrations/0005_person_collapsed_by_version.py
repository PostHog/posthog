import json
from dataclasses import dataclass
from functools import cached_property
from typing import Dict, List, Optional, Tuple, cast

import structlog
from clickhouse_driver.errors import ServerException
from django.conf import settings
from django.utils.timezone import now
from ee.clickhouse.sql.clickhouse import STORAGE_POLICY
from ee.clickhouse.sql.person import PERSONS_TABLE_ENGINE

from posthog.async_migrations.utils import execute_op_clickhouse
from ee.clickhouse.sql.events import EVENTS_TABLE_JSON_MV_SQL, KAFKA_EVENTS_TABLE_JSON_SQL
from ee.clickhouse.sql.table_engines import MergeTreeEngine, ReplacingMergeTree
from posthog.async_migrations.definition import (
    AsyncMigrationDefinition,
    AsyncMigrationOperation,
    AsyncMigrationOperationSQL,
)
from posthog.client import sync_execute
from posthog.constants import AnalyticsDBMS
from posthog.errors import lookup_error_code
from posthog.models.instance_setting import set_instance_setting
from posthog.models.person.person import Person
from posthog.redis import get_client
from posthog.utils import flatten

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
PG_COPY_INSERT_TIMESTAMP = '2020-01-01 00:00:00.000000'


def optimize_table_fn(query_id):
    default_timeout = settings.ASYNC_MIGRATIONS_DEFAULT_TIMEOUT_SECONDS
    try:
        execute_op_clickhouse(
            f"OPTIMIZE TABLE {PERSON_TABLE} FINAL",
            query_id,
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
            # :TODO: Copy data from postgres
            # :TODO: "fix" mv tables
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
    def pg_copy_target_person_id(self):
        # :TRICKY: We calculate the last ID to copy at the start of migration once and cache it.
        #    If the migration gets e.g. restarted, this is recalculated.
        return Person.objects.latest("id").id

    def get_pg_copy_highwatermark(self) -> Tuple[int, int]:
        highwatermark = get_client().get(REDIS_HIGHWATERMARK_KEY)
        return highwatermark if highwatermark is not None else 0

    def _copy_batch_from_postgres(self) -> bool:
        highwatermark = self.get_pg_copy_highwatermark()
        if highwatermark > self.pg_copy_target_person_id:
            logger.info(
                "Finished copying people from postgres to clickhouse",
                highwatermark=highwatermark,
                pg_copy_target_person_id=self.pg_copy_target_person_id,
            )
            return False

        persons = list(Person.objects.filter(id__gte=highwatermark)[:PG_COPY_BATCH_SIZE])

        # :TODO: This has a sql injection risk!
        sync_execute(
            f"""
            INSERT INTO {TEMPORARY_TABLE_NAME} (id, created_at, team_id, properties, is_identified, _timestamp, _offset, is_deleted, version)
            VALUES {', '.join(self._person_ch_insert_values(person) for person in persons)}
            """
        )

        new_highwatermark = (persons[-1].id if len(persons) > 0 else self.pg_copy_target_person_id) + 1
        get_client().set(REDIS_HIGHWATERMARK_KEY, new_highwatermark)
        logger.debug(
            "Copied batch of people from postgres to clickhouse",
            highwatermark=highwatermark,
            new_highwatermark=new_highwatermark,
            pg_copy_target_person_id=self.pg_copy_target_person_id,
        )
        return True

    def _person_ch_insert_values(self, person: Person) -> str:
        # :TRICKY: We use a custom timestamp to identify these rows
        created_at = person.created_at.strftime("%Y-%m-%d %H:%M:%S.%f")
        return f"('{person.uuid}', '{created_at}', {person.team_id}, '{json.dumps(person.properties)}', {'1' if person.is_identified else '0'}, '{PG_COPY_INSERT_TIMESTAMP}', 0, 0, {person.version or 0})"
