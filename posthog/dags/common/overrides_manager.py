import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

from clickhouse_driver import Client

from posthog import settings
from posthog.clickhouse.cluster import AlterTableMutationRunner, LightweightDeleteMutationRunner
from posthog.dags.common.staged_dictionary import StagedDictionary
from posthog.dataclasses import frozen

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

    def exists(self, client: Client) -> bool:
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


TOverridesSnapshotTable = TypeVar("TOverridesSnapshotTable", bound=OverridesSnapshotTable)


@frozen
class OverridesSnapshotDictionary(ABC, Generic[TOverridesSnapshotTable]):
    source: TOverridesSnapshotTable

    @property
    def name(self) -> str:
        return f"{self.source.name}_dictionary"

    @property
    def qualified_name(self):
        return f"{settings.CLICKHOUSE_DATABASE}.{self.name}"

    @abstractmethod
    def create(
        self,
        client: Client,
        shards: int,
        max_execution_time: int,
        max_memory_usage: int,
        query: str | None = None,
    ) -> None:
        """``query`` overrides the SOURCE, for a host that cannot see the snapshot table."""
        raise NotImplementedError()

    @abstractmethod
    def staged(self) -> StagedDictionary:
        """Where this dictionary's rows go so another cluster can load them.

        Keyed by the dictionary's own name, never by anything per-run, because CREATE ... IF NOT
        EXISTS keys on that same name and a dictionary outlives the run that created it.
        """
        raise NotImplementedError()

    def recreate(
        self,
        client: Client,
        shards: int,
        max_execution_time: int,
        max_memory_usage: int,
        query: str | None = None,
    ) -> None:
        """Replace the dictionary, so no definition an earlier run left behind can survive."""
        self.drop(client)
        self.create(client, shards, max_execution_time, max_memory_usage, query)

    def exists(self, client: Client) -> bool:
        results = client.execute(
            "SELECT count() FROM system.dictionaries WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": self.name},
        )
        [[count]] = results
        return count > 0

    def drop(self, client: Client) -> None:
        client.execute(f"DROP DICTIONARY IF EXISTS {self.qualified_name} SYNC")

    def __is_loaded(self, client: Client) -> bool:
        results = client.execute(
            "SELECT status, last_exception FROM system.dictionaries WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": self.name},
        )
        if not results:
            raise Exception("dictionary does not exist")
        else:
            [[status, last_exception]] = results
            if status == "LOADED":
                return True
            elif status in {"LOADING", "FAILED_AND_RELOADING", "LOADED_AND_RELOADING"}:
                return False
            elif status == "FAILED":
                raise Exception(f"failed to load: {last_exception}")
            else:
                raise Exception(f"unexpected status: {status}")

    @abstractmethod
    def get_checksum(self, client: Client):
        raise NotImplementedError()

    def load(self, client: Client):
        # TODO: this should probably not reload if the dictionary is already loaded
        client.execute(f"SYSTEM RELOAD DICTIONARY {self.qualified_name}")

        # reload is async, so we need to wait for the dictionary to actually be loaded
        # TODO: this should probably throw on unexpected reloads
        while not self.__is_loaded(client):
            time.sleep(5.0)

        return self.get_checksum(client)

    @property
    @abstractmethod
    def update_table(self):
        raise NotImplementedError()

    @property
    @abstractmethod
    def update_commands(self):
        raise NotImplementedError()

    @property
    def update_mutation_runner(self) -> AlterTableMutationRunner:
        return AlterTableMutationRunner(
            table=self.update_table,
            commands=self.update_commands,
            parameters={"name": self.qualified_name},
        )

    @property
    @abstractmethod
    def overrides_table(self):
        raise NotImplementedError()

    @property
    @abstractmethod
    def overrides_deletes_predicate(self):
        raise NotImplementedError()

    @property
    def overrides_delete_mutation_runner(self) -> LightweightDeleteMutationRunner:
        return LightweightDeleteMutationRunner(
            table=self.overrides_table,
            predicate=self.overrides_deletes_predicate,
            parameters={"name": self.qualified_name},
        )
