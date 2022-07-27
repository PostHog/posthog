from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from posthog.constants import AnalyticsDBMS
from posthog.models.utils import sane_repr
from posthog.settings import ASYNC_MIGRATIONS_DEFAULT_TIMEOUT_SECONDS
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
    started_at: datetime
    finished_at: datetime
    posthog_min_version: str
    posthog_max_version: str


class AsyncMigrationOperation:
    def __init__(
        self, fn: Callable[[str], None], rollback_fn: Callable[[str], None] = lambda _: None,
    ):
        self.fn = fn

        # This should not be a long operation as it will be executed synchronously!
        # Defaults to a no-op ("") - None causes a failure to rollback
        self.rollback_fn = rollback_fn


class AsyncMigrationOperationSQL(AsyncMigrationOperation):
    def __init__(
        self,
        *,
        sql: str,
        sql_settings: Optional[Dict] = None,
        rollback: Optional[str],
        rollback_settings: Optional[Dict] = None,
        database: AnalyticsDBMS = AnalyticsDBMS.CLICKHOUSE,
        timeout_seconds: int = ASYNC_MIGRATIONS_DEFAULT_TIMEOUT_SECONDS,
        per_shard: bool = False
    ):
        self.sql = sql
        self.sql_settings = sql_settings
        self.rollback = rollback
        self.rollback_settings = rollback_settings
        self.database = database
        self.timeout_seconds = timeout_seconds
        self.per_shard = per_shard

    def fn(self, query_id: str):
        self._execute_op(query_id, self.sql, self.sql_settings)

    def rollback_fn(self, query_id: str):
        if self.rollback is not None:
            self._execute_op(query_id, self.rollback, self.rollback_settings)

    def _execute_op(self, query_id: str, sql: str, settings: Optional[Dict]):
        from posthog.async_migrations.utils import execute_op_clickhouse, execute_op_postgres

        if self.database == AnalyticsDBMS.CLICKHOUSE:
            execute_op_clickhouse(
                sql,
                query_id=query_id,
                timeout_seconds=self.timeout_seconds,
                settings=settings,
                per_shard=self.per_shard,
            )
        else:
            execute_op_postgres(sql, query_id)

    __repr__ = sane_repr("sql", "rollback", "database", "timeout_seconds", include_id=False)


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

    # run before creating the migration model. Returns a boolean specifying if the instance should
    # set up the AsyncMigration model and show this migration in the UI
    def is_hidden(self) -> bool:
        return False

    # will be run before starting the migration, return a boolean specifying if the instance needs this migration
    # e.g. instances where fresh setups are already set up correctly
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
