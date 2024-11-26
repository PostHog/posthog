from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import NamedTuple, TypeVar

from clickhouse_driver import Client
from clickhouse_pool import ChPool
from django.conf import settings

from posthog.clickhouse.client.connection import make_ch_pool


K = TypeVar("K")
V = TypeVar("V")


class FuturesMap(dict[K, Future[V]]):
    def wait(self, *args, **kwargs) -> tuple[FuturesMap[K, V], FuturesMap[K, V]]:
        reverse_map = {v: k for k, v in self.items()}
        assert len(reverse_map) == len(self)

        done_futures, not_done_futures = wait(self.values(), *args, **kwargs)
        return (
            FuturesMap({reverse_map[f]: f for f in done_futures}),
            FuturesMap({reverse_map[f]: f for f in not_done_futures}),
        )


class ConnectionInfo(NamedTuple):
    address: str
    port: int


class HostInfo(NamedTuple):
    connection_info: ConnectionInfo
    shard_num: int | None
    replica_num: int | None


T = TypeVar("T")


class ClickhouseCluster:
    def __init__(self, bootstrap_client: Client, extra_hosts: Sequence[ConnectionInfo] | None = None) -> None:
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
        if extra_hosts is not None:
            self.hosts.extend(
                [HostInfo(connection_info, shard_num=None, replica_num=None) for connection_info in extra_hosts]
            )
        self.__pools: dict[HostInfo, ChPool] = {}

    def __get_pool(self, host: HostInfo) -> ChPool:
        pool = self.__pools.get(host)
        if pool is None:
            pool = self.__pools[host] = make_ch_pool(host=host.connection_info.address, port=host.connection_info.port)
        return pool

    def map_hosts(self, fn: Callable[[Client], T]) -> FuturesMap[HostInfo, T]:
        def task(pool):
            with pool.get_client() as client:
                return fn(client)

        with ThreadPoolExecutor() as executor:
            return FuturesMap({host: executor.submit(task, self.__get_pool(host)) for host in self.hosts})

    def map_shards(self, fn: Callable[[Client], T]) -> FuturesMap[int, T]:
        def task(pool):
            with pool.get_client() as client:
                return fn(client)

        shard_hosts: dict[int, HostInfo] = {}
        for host in self.hosts:
            if host.shard_num is not None and host.shard_num not in shard_hosts:
                shard_hosts[host.shard_num] = host

        with ThreadPoolExecutor() as executor:
            return FuturesMap(
                {shard_num: executor.submit(task, self.__get_pool(host)) for shard_num, host in shard_hosts.items()}
            )
