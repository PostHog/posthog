from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional, Union

from posthog.constants import AnalyticsDBMS
from posthog.models.utils import sane_repr
from posthog.settings import ASYNC_MIGRATIONS_DEFAULT_TIMEOUT_SECONDS
from posthog.version_requirement import ServiceVersionRequirement

if TYPE_CHECKING:
    from posthog.models.async_migration import AsyncMigration


class AsyncMigrationOperation:
    def __init__(
        self,
        fn: Callable[[str], None],
        rollback_fn: Callable[[str], None] = lambda _: None,
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
        sql_settings: Optional[dict] = None,
        rollback: Optional[str],
        rollback_settings: Optional[dict] = None,
        database: AnalyticsDBMS = AnalyticsDBMS.CLICKHOUSE,
        timeout_seconds: int = ASYNC_MIGRATIONS_DEFAULT_TIMEOUT_SECONDS,
        per_shard: bool = False,
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

    def _execute_op(self, query_id: str, sql: str, settings: Optional[dict]):
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
    name: str

    # the migration cannot be run before this version
    posthog_min_version = "0.0.0"

    # the migration _must_ be run before this version
    posthog_max_version = "10000.0.0"

    # use this to add information about why this migration is needed to self-hosted users
    description = ""

    # list of versions accepted for the services the migration relies on e.g. ClickHouse, Postgres
    service_version_requirements: list[ServiceVersionRequirement] = []

    # list of operations the migration will perform _in order_
    operations: list[AsyncMigrationOperation] = []

    # name of async migration this migration depends on
    depends_on: Optional[str] = None

    # optional parameters for this async migration. Shown in the UI when starting the migration
    parameters: dict[str, tuple[(Optional[Union[int, str]], str, Callable[[Any], Any])]] = {}

    def __init__(self, name: str):
        self.name = name

    # will be run before starting the migration, return a boolean specifying if the instance needs this migration
    # e.g. instances where fresh setups are already set up correctly
    def is_required(self) -> bool:
        return True

    # run before starting the migration
    def precheck(self) -> tuple[bool, Optional[str]]:
        return (True, None)

    # run at a regular interval while the migration is being executed
    def healthcheck(self) -> tuple[bool, Optional[str]]:
        return (True, None)

    # return an int between 0-100 to specify how far along this migration is
    def progress(self, migration_instance: "AsyncMigration") -> int:
        return int(100 * migration_instance.current_operation_index / len(self.operations))

    # returns the async migration instance for this migration. Only works during the migration
    def migration_instance(self) -> "AsyncMigration":
        from posthog.models.async_migration import AsyncMigration

        return AsyncMigration.objects.get(name=self.name)

    def get_parameter(self, parameter_name: str):
        instance = self.migration_instance()
        if parameter_name in instance.parameters:
            return instance.parameters[parameter_name]
        else:
            # Return the default value
            return self.parameters[parameter_name][0]
