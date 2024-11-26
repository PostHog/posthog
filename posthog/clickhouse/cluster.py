from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from typing import NamedTuple, TypeVar

from clickhouse_driver import Client
from clickhouse_pool import ChPool
from django.conf import settings

from posthog.clickhouse.client.connection import make_ch_pool


class ConnectionInfo(NamedTuple):
    address: str
    port: int


class HostInfo(NamedTuple):
    connection_info: ConnectionInfo
    shard_num: int | None
    replica_num: int | None


T = TypeVar("T")


class ClickhouseCluster:
    def __init__(self, bootstrap_client: Client) -> None:
        self.hosts = [
            HostInfo(ConnectionInfo(host_address, port), shard_num, replica_num)
            for (host_address, port, shard_num, replica_num) in bootstrap_client.execute(
                """
                SELECT host_address, port, shard_num, replica_num
                FROM system.clusters
                WHERE name = %(name)s
                ORDER BY shard_num, replica_num
                """,
                {"name": settings.CLICKHOUSE_CLUSTER},
            )
        ]
        self.__pools: dict[HostInfo, ChPool] = {}

    def __get_pool(self, host: HostInfo) -> ChPool:
        pool = self.__pools.get(host)
        if pool is None:
            pool = self.__pools[host] = make_ch_pool(host=host.connection_info.address, port=host.connection_info.port)
        return pool

    def map_hosts(self, fn: Callable[[Client], T]) -> Mapping[HostInfo, Future[T]]:
        def task(pool):
            with pool.get_client() as client:
                return fn(client)

        with ThreadPoolExecutor() as executor:
            return {host: executor.submit(task, self.__get_pool(host)) for host in self.hosts}

    def map_shards(self, fn: Callable[[Client], T]) -> Mapping[int, Future[T]]:
        def task(pool):
            with pool.get_client() as client:
                return fn(client)

        shard_hosts: dict[int, HostInfo] = {}
        for host in self.hosts:
            if host.shard_num not in shard_hosts:
                shard_hosts[host.shard_num] = host

        with ThreadPoolExecutor() as executor:
            return {shard_num: executor.submit(task, self.__get_pool(host)) for shard_num, host in shard_hosts.items()}
