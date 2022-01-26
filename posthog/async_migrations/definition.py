from datetime import datetime
from typing import Callable, List, Optional, Tuple

from posthog.constants import AnalyticsDBMS
from posthog.version_requirement import ServiceVersionRequirement


# used to prevent circular imports
class AsyncMigrationType:
    id: int
    name: str
    description: str
    progress: int
    status: int
    current_operation_index: int
    current_query_id: str
    celery_task_id: str
    started_at: str
    finished_at: datetime
    posthog_min_version: str
    posthog_max_version: str


class AsyncMigrationOperation:
    def __init__(
        self,
        fn: Callable[[str], None],
        rollback_fn: Callable[[str], None] = lambda _: None,
        resumable=False,
        sql: Optional[str] = None,
    ):
        self.fn = fn
        # if the operation is dynamic and knows how to restart correctly after a crash
        # Example:
        #   - Not resumable: `INSERT INTO table1 (col1) SELECT col1 FROM table2`
        #   - Resumable: `INSERT INTO table2 (foo, timestamp) SELECT foo, timestamp FROM table1 WHERE timestamp > (SELECT max(timestamp) FROM table2)`
        self.resumable = resumable

        # This should not be a long operation as it will be executed synchronously!
        # Defaults to a no-op ("") - None causes a failure to rollback
        self.rollback_fn = rollback_fn

        # If the operation specifies raw SQL, add this as a property for easier debugging
        self.sql = sql

    @classmethod
    def simple_op(
        cls,
        sql,
        rollback=None,
        database: AnalyticsDBMS = AnalyticsDBMS.CLICKHOUSE,
        resumable=False,
        timeout_seconds: int = 60,
    ):
        return cls(
            fn=cls.get_db_op(database=database, sql=sql, timeout_seconds=timeout_seconds),
            rollback_fn=cls.get_db_op(database=database, sql=rollback) if rollback else lambda _: None,
            resumable=resumable,
            sql=sql,
        )

    @classmethod
    def get_db_op(cls, sql: str, database: AnalyticsDBMS = AnalyticsDBMS.CLICKHOUSE, timeout_seconds: int = 60):
        from posthog.async_migrations.utils import execute_op_clickhouse, execute_op_postgres

        # timeout is currently CH only
        def run_db_op(query_id):
            if database == AnalyticsDBMS.CLICKHOUSE:
                execute_op_clickhouse(sql, query_id, timeout_seconds)
            else:
                execute_op_postgres(sql, query_id)

        return run_db_op


class AsyncMigrationDefinition:

    # the migration cannot be run before this version
    posthog_min_version = "0.0.0"

    # the migration _must_ be run before this version
    posthog_max_version = "10000.0.0"

    # use this to add information about why this migration is needed to self-hosted users
    description = ""

    # list of versions accepted for the services the migration relies on e.g. ClickHouse, Postgres
    service_version_requirements: List[ServiceVersionRequirement] = []

    # list of operations the migration will perform _in order_
    operations: List[AsyncMigrationOperation] = []

    # name of async migration this migration depends on
    depends_on: Optional[str] = None

    # will be run before starting the migration, return a boolean specifying if the instance needs this migration
    # e.g. instances with CLICKHOUSE_REPLICATION == True might need different migrations
    def is_required(self) -> bool:
        return True

    # run before starting the migration
    def precheck(self) -> Tuple[bool, Optional[str]]:
        return (True, None)

    # run at a regular interval while the migration is being executed
    def healthcheck(self) -> Tuple[bool, Optional[str]]:
        return (True, None)

    # return an int between 0-100 to specify how far along this migration is
    def progress(self, migration_instance: AsyncMigrationType) -> int:
        return int(100 * migration_instance.current_operation_index / len(self.operations))
