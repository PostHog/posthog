import re
from dataclasses import dataclass
from functools import cached_property
from typing import Dict, List, Optional, cast

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
- We can't use a second kafka consumer for the new table due to data integrity concerns, so we're leveraging
    multiple materialized views.
- Copying `persons` from postgres will be the slow part here and should be resumable. We leverage the fact
    person ids are monotonically increasing for this reason.
"""


TEMPORARY_TABLE_NAME = f"{settings.CLICKHOUSE_DATABASE}.temp_events_0005_person_collapsed_by_version"
PERSON_TABLE = "person"
PERSON_TABLE_NAME = f"{settings.CLICKHOUSE_DATABASE}.{PERSON_TABLE}"
BACKUP_TABLE_NAME = f"{PERSON_TABLE_NAME}_backup_0005_person_collapsed_by_version"
FAILED_PERSON_TABLE_NAME = f"{PERSON_TABLE_NAME}_failed_person_collapsed_by_version"


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
