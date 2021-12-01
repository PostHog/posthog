from datetime import datetime
from typing import List, Optional, Tuple

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
    def __init__(self, sql="", database="clickhouse", timeout_seconds=60, rollback=None, resumable=False):
        self.sql = sql
        self.database = database
        self.timeout_seconds = timeout_seconds
        self.resumable = resumable
        self.rollback = rollback


class SpecialMigrationDefinition:
    posthog_min_version = "0.0.0"
    posthog_max_version = "10000.0.0"
    description = ""

    service_version_requirements: List[ServiceVersionRequirement] = []
    operations: List[SpecialMigrationOperation] = []
    dependencies: List[str] = []

    def is_required(self) -> bool:
        return True

    def healthcheck(self) -> Tuple[bool, Optional[str]]:
        return (True, None)

    def progress(self, migration_instance: SpecialMigrationType) -> int:
        return int(100 * migration_instance.current_operation_index / len(self.operations))

    def rollback(self, migration_instance: SpecialMigrationType) -> Tuple[bool, Optional[str]]:
        return (False, None)
