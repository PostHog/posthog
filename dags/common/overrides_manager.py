import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

# Forward declaration for type hints - actual import at bottom to avoid circular dependency
from typing import TYPE_CHECKING

from clickhouse_driver import Client

from posthog import settings

if TYPE_CHECKING:
    pass


@dataclass
class OverridesSnapshotTable(ABC):
    id: uuid.UUID

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError()

    @property
    def qualified_name(self):
        return f"{settings.CLICKHOUSE_DATABASE}.{self.name}"

    @abstractmethod
    def create(self, client: Client) -> None:
        raise NotImplementedError()

    def exists(self, client: Client) -> None:
        results = client.execute(
            f"SELECT count() FROM system.tables WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": self.name},
        )
        [[count]] = results
        return count > 0

    def drop(self, client: Client) -> None:
        client.execute(f"DROP TABLE IF EXISTS {self.qualified_name} SYNC")

    @abstractmethod
    def populate(self, client: Client, timestamp: str, limit: int | None = None) -> None:
        raise NotImplementedError()

    def sync(self, client: Client) -> None:
        client.execute(f"SYSTEM SYNC REPLICA {self.qualified_name} STRICT")

        # this is probably excessive (and doesn't guarantee that anybody else won't mess with the table later) but it
        # probably doesn't hurt to be careful
        [[queue_size]] = client.execute(
            "SELECT queue_size FROM system.replicas WHERE database = %(database)s AND table = %(table)s",
            {"database": settings.CLICKHOUSE_DATABASE, "table": self.name},
        )
        assert queue_size == 0
