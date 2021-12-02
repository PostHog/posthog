from datetime import datetime
from typing import Callable, List, Optional, Tuple

from posthog.constants import AnalyticsDBMS
from posthog.version_requirement import ServiceVersionRequirement


# used to prevent circular imports
class SpecialMigrationType:
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
    last_error: str
    posthog_min_version: str
    posthog_max_version: str


class SpecialMigrationOperation:
    def __init__(
        self,
        sql="",
        database: AnalyticsDBMS = "clickhouse",
        timeout_seconds: int = 60,
        rollback: Callable[..., SpecialMigrationType] = None,
        resumable=False,
    ):
        self.sql = sql
        self.database = database

        # currently CH only
        self.timeout_seconds = timeout_seconds

        # if the operation is dynamic and knows how to restart correctly after a crash
        # Example:
        #   - Not resumable: `INSERT INTO table1 (col1) SELECT col1 FROM table2`
        #   - Resumable: `INSERT INTO table2 (foo, timestamp) SELECT foo, timestamp FROM table1 WHERE timestamp > (SELECT max(timestamp) FROM table2)`
        self.resumable = resumable

        self.rollback = rollback


class SpecialMigrationDefinition:

    # the migration cannot be run before this version
    posthog_min_version = "0.0.0"

    # the migration _must_ be run before this version
    posthog_max_version = "10000.0.0"

    # use this to add information about why this migration is needed to self-hosted users
    description = ""

    # list of versions accepted for the services the migration relies on e.g. ClickHouse, Postgres
    service_version_requirements: List[ServiceVersionRequirement] = []

    # list of operations the migration will perform _in order_
    operations: List[SpecialMigrationOperation] = []

    # other special migrations this migration depends on
    dependencies: List[str] = []

    # will be run before starting the migration, return a boolean specifying if the instance needs this migration
    def is_required(self) -> bool:
        return True

    # run before the migration and at regular intervals
    def healthcheck(self) -> Tuple[bool, Optional[str]]:
        return (True, None)

    # return an int between 0-100 to specify how far along this migration is
    def progress(self, migration_instance: SpecialMigrationType) -> int:
        return int(100 * migration_instance.current_operation_index / len(self.operations))

    # a function we'll try to run if the migration fails to roll it back, can also be triggered manually
    def rollback(self, migration_instance: SpecialMigrationType) -> Tuple[bool, Optional[str]]:
        return (False, None)
