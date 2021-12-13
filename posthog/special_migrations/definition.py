from typing import Callable, List, Optional, Tuple

from posthog.models.special_migration import SpecialMigration
from posthog.version_requirement import ServiceVersionRequirement


class SpecialMigrationOperation:
    def __init__(
        self,
        sql: str = "",
        database: str = "clickhouse",
        timeout_seconds: int = 60,
        rollback: str = None,
        resumable: bool = False,
        side_effect: Callable = lambda: None,
    ):
        self.sql = sql
        self.database = database
        self.timeout_seconds = timeout_seconds
        self.resumable = resumable
        self.rollback = rollback
        self.side_effect = side_effect


class SpecialMigrationDefinition:
    posthog_min_version = "0.0.0"
    posthog_max_version = "10000.0.0"

    service_version_requirements: List[ServiceVersionRequirement] = []
    operations: List[SpecialMigrationOperation] = []
    dependencies: List[str]

    def is_required(self) -> bool:
        return True

    def healthcheck(self) -> Tuple[bool, Optional[str]]:
        return (True, None)

    def progress(self, migration_instance: SpecialMigration) -> int:
        return int(100 * migration_instance.current_operation_index / len(self.operations))

    def rollback(self, migration_instance: SpecialMigration) -> Tuple[bool, Optional[str]]:
        return (False, None)
