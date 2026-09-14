"""clickhouse_driver client that keeps the CPU time ClickHouse reports for each query.

ClickHouse streams a ProfileEvents block on the query's connection every `interactive_delay`,
one row per host and counter, and the initiator forwards the remote shards' counters in the
same stream. The driver parses each block to stay in sync with the protocol and then drops it.
This client keeps the CPU counter on `last_query`, next to the byte progress the driver already
keeps, so the caller can meter CPU at the same point it meters bytes and without a second trip
to the query log.

The driver also clears `last_query` when it disconnects after a server-side error, before the
exception reaches the caller. This client keeps that query info as `last_failed_query` so a
query killed by a timeout or a read limit can still be metered for what it read.

The pool only creates this client while the CLICKHOUSE_METERED_CLIENT instance setting is on.
Callers must treat `cpu_microseconds` and `last_failed_query` as optional.

Exports:
* MeteredClient
* MeteredChPool
* cpu_microseconds_from_profile_events
* metered_client_enabled
"""

import time
from functools import lru_cache
from typing import Any, Optional

from clickhouse_driver import Client
from clickhouse_driver.connection import Connection
from clickhouse_driver.protocol import ServerPacketTypes
from clickhouse_pool import ChPool

from posthog.exceptions_capture import capture_exception
from posthog.settings import TEST

CPU_COUNTER = "OSCPUVirtualTimeMicroseconds"
_METERED_MARKER = "_posthog_metered"


def metered_client_enabled() -> bool:
    """The CLICKHOUSE_METERED_CLIENT instance setting, re-read once a minute. Decided per new
    connection, so flipping it reaches the pool as connections are opened, without a deploy."""
    if TEST:
        return True
    return _metered_client_enabled(round(time.time() / 60))


@lru_cache(maxsize=1)
def _metered_client_enabled(_ttl: int) -> bool:
    from posthog.models.instance_setting import (
        get_instance_setting,  # noqa: PLC0415 - avoids a Django model import at client import time
    )

    try:
        return bool(get_instance_setting("CLICKHOUSE_METERED_CLIENT"))
    except Exception:
        # posthog_instancesetting may not exist yet during initial Postgres migrations.
        return False


def cpu_microseconds_from_profile_events(block: Any) -> int:
    columns = [name for name, _ in block.columns_with_types]
    try:
        name_index = columns.index("name")
        type_index = columns.index("type")
        value_index = columns.index("value")
    except ValueError:
        return 0
    total = 0
    for row in block.get_rows():
        # An `increment` row is the delta since the previous block. A `gauge` row is an
        # absolute value, so adding it would count the same CPU on every block.
        if row[name_index] == CPU_COUNTER and row[type_index] == "increment":
            total += int(row[value_index])
    return total


class MeteredClient(Client):
    last_failed_query: Optional[Any] = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._meter_connection(self.connection)

    def get_connection(self) -> Connection:
        # The driver rotates through `self.connections` when alternative hosts are configured,
        # so every connection it hands back has to carry the hook, not only the first one.
        connection = super().get_connection()
        self._meter_connection(connection)
        return connection

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        # Cleared per query so a connect failure can never surface an older query's info.
        self.last_failed_query = None
        return super().execute(*args, **kwargs)

    def disconnect_connection(self) -> None:
        # The driver disconnects more than once on a failure, and only the first call still
        # has the query info.
        if self.last_query is not None:
            self.last_failed_query = self.last_query
        super().disconnect_connection()

    def _meter_connection(self, connection: Connection) -> None:
        if getattr(connection, _METERED_MARKER, False):
            return
        receive_packet = connection.receive_packet

        def receive_packet_and_meter_cpu() -> Any:
            packet = receive_packet()
            if packet.type == ServerPacketTypes.PROFILE_EVENTS and getattr(packet, "block", None) is not None:
                query_info = self.last_query
                if query_info is not None:
                    # A parser failure must never fail the query it is metering.
                    try:
                        query_info.cpu_microseconds = getattr(query_info, "cpu_microseconds", 0) + (
                            cpu_microseconds_from_profile_events(packet.block)
                        )
                    except Exception as e:
                        capture_exception(e)
            return packet

        connection.receive_packet = receive_packet_and_meter_cpu  # ty: ignore[invalid-assignment]
        setattr(connection, _METERED_MARKER, True)


class MeteredChPool(ChPool):
    def _connect(self, key: Optional[str] = None) -> Client:
        client_class = MeteredClient if metered_client_enabled() else Client
        client = client_class(**self.connection_args)
        if key is not None:
            self._used[key] = client
            self._rused[id(client)] = key
        else:
            self._pool.append(client)
        return client
