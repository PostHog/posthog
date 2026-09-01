"""One ClickHouse dictionary definition, created on every host and loaded until they all agree.

Every dictionary-driven deletion job builds the same thing: a dictionary over a small worklist
table, created on each host, loaded, and checksummed so every host is proven to hold the same
rows before a mutation joins it. Subclasses supply the identity (name, columns, key, source
query, credentials); this base owns the lifecycle so there is one implementation of create,
load-with-deadline, checksum and drop.

Staging across clusters (``staged``) is declared here because ``staged_dictionary`` needs it on
every dictionary it can carry. A subclass whose contents change during a run must refuse it: a
staged copy is a static object, so a reload on the far cluster would not see the change.
"""

import abc
import time

from django.conf import settings

from clickhouse_driver.client import Client

from posthog.clickhouse.client.connection import ClickHouseCredentials, ClickHouseUser, get_clickhouse_creds
from posthog.dags.common.staged_dictionary import StagedDictionary
from posthog.dataclasses import frozen

# A dictionary wedged in LOADING would otherwise hold a run open forever and silently: a run that
# hangs raises no failure alert, while one that times out does.
DEFAULT_DICTIONARY_LOAD_TIMEOUT: float = 1800.0


@frozen
class Dictionary(abc.ABC):
    load_timeout: float = DEFAULT_DICTIONARY_LOAD_TIMEOUT

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unqualified dictionary name; the subclass owns the naming scheme."""

    @property
    @abc.abstractmethod
    def schema(self) -> str:
        """Column declarations, e.g. ``team_id Int64, key String``."""

    @property
    @abc.abstractmethod
    def primary_key(self) -> str:
        """Comma-separated key columns."""

    @property
    @abc.abstractmethod
    def query(self) -> str:
        """The SELECT the dictionary source runs against ClickHouse."""

    @abc.abstractmethod
    def staged(self) -> StagedDictionary:
        """Where this dictionary's rows go so another cluster can load them; see StagedDictionary.

        Keyed by the dictionary's own name, never by anything per-run. A dictionary outlives the
        run that created it, and CREATE ... IF NOT EXISTS keys on that same name, so a per-run key
        would leave the earlier definition pointing at an object no later run writes.
        """

    @property
    def credentials(self) -> ClickHouseCredentials:
        """Credentials the dictionary source reads as.

        Defaults to the default user. Override only when the role's SELECT grants on the source
        tables are known to exist in every environment; grants live in infra, not this repo.
        """
        return get_clickhouse_creds(ClickHouseUser.DEFAULT)

    @property
    def qualified_name(self) -> str:
        return f"{settings.CLICKHOUSE_DATABASE}.{self.name}"

    def create(
        self,
        client: Client,
        shards: int,
        max_execution_time: int,
        max_memory_usage: int,
        query: str | None = None,
    ) -> None:
        """``query`` overrides the SOURCE query, for a host that cannot see the source table."""
        # Credentials are query parameters so they stay out of the traced statement.
        creds = self.credentials
        client.execute(
            f"""
            CREATE DICTIONARY IF NOT EXISTS {self.qualified_name} ({self.schema})
            PRIMARY KEY {self.primary_key}
            SOURCE(CLICKHOUSE(DB %(database)s USER %(user)s PASSWORD %(password)s QUERY %(query)s))
            LAYOUT(COMPLEX_KEY_HASHED(SHARDS {shards}))
            LIFETIME(0)
            SETTINGS(max_execution_time={max_execution_time}, max_memory_usage={max_memory_usage})
            """,
            {
                "database": settings.CLICKHOUSE_DATABASE,
                "user": creds.user,
                "password": creds.password,
                "query": query or self.query,
            },
        )

    def recreate(
        self,
        client: Client,
        shards: int,
        max_execution_time: int,
        max_memory_usage: int,
        query: str | None = None,
    ) -> None:
        """Replace the dictionary, so no definition an earlier run left behind can survive.

        CREATE ... IF NOT EXISTS keeps the existing source, which is right where that source is the
        replicated table and wrong where it is a staged object whose query can change between
        deploys.
        """
        self.drop(client)
        self.create(client, shards, max_execution_time, max_memory_usage, query)

    def exists(self, client: Client) -> bool:
        [[count]] = client.execute(
            "SELECT count() FROM system.dictionaries WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": self.name},
        )
        return count > 0

    def drop(self, client: Client) -> None:
        client.execute(f"DROP DICTIONARY IF EXISTS {self.qualified_name} SYNC")

    def is_loaded(self, client: Client) -> bool:
        results = client.execute(
            "SELECT status, last_exception FROM system.dictionaries WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": self.name},
        )
        if not results:
            raise Exception(f"{self.qualified_name} does not exist")
        [[status, last_exception]] = results
        if status == "LOADED":
            return True
        if status in {"LOADING", "FAILED_AND_RELOADING", "LOADED_AND_RELOADING"}:
            return False
        if status == "FAILED":
            raise Exception(f"{self.qualified_name} failed to load: {last_exception}")
        raise Exception(f"{self.qualified_name} in unexpected status: {status}")

    def load(self, client: Client) -> int:
        """Reload on this host, wait for it to finish within ``load_timeout``, and return the checksum."""
        client.execute(f"SYSTEM RELOAD DICTIONARY {self.qualified_name}")

        # The reload is asynchronous, so a consumer would read a half-populated dictionary
        # without this wait.
        deadline = time.monotonic() + self.load_timeout
        while not self.is_loaded(client):
            if time.monotonic() > deadline:
                raise Exception(f"{self.qualified_name} still not loaded after {self.load_timeout:.0f}s")
            time.sleep(5.0)

        return self.checksum(client)

    def checksum(self, client: Client) -> int:
        # XOR of per-row hashes is order independent, so hosts holding the same entries agree
        # regardless of read order and no sort is needed. cityHash64(*) covers every declared
        # column, attributes included: a consumer reads attributes from whichever host it lands
        # on, so hosts must agree on more than the key set.
        [[checksum]] = client.execute(f"SELECT groupBitXor(cityHash64(*)) FROM {self.qualified_name}")
        return checksum
