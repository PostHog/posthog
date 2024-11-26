from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ALL_COMPLETED, FIRST_EXCEPTION, Future, ThreadPoolExecutor, as_completed, wait
from typing import NamedTuple, TypeVar

from clickhouse_driver import Client
from clickhouse_pool import ChPool
from django.conf import settings

from posthog.clickhouse.client.connection import make_ch_pool


K = TypeVar("K")
V = TypeVar("V")


class FuturesMap(dict[K, Future[V]]):
    def as_completed(self, *args, **kwargs) -> Iterator[tuple[K, Future[V]]]:
        reverse_map = {v: k for k, v in self.items()}
        assert len(reverse_map) == len(self)

        for f in as_completed(self.values()):
            yield reverse_map[f], f

    def wait(self, *args, **kwargs) -> tuple[FuturesMap[K, V], FuturesMap[K, V]]:
        reverse_map = {v: k for k, v in self.items()}
        assert len(reverse_map) == len(self)

        done_futures, not_done_futures = wait(self.values(), *args, **kwargs)
        return (
            FuturesMap({reverse_map[f]: f for f in done_futures}),
            FuturesMap({reverse_map[f]: f for f in not_done_futures}),
        )

    def result(
        self, timeout: float | int | None = None, return_when: FIRST_EXCEPTION | ALL_COMPLETED = ALL_COMPLETED
    ) -> dict[K, V]:
        results = {}
        errors = {}
        for k, future in self.as_completed(timeout=timeout):
            try:
                results[k] = future.result()
            except Exception as e:
                if return_when is FIRST_EXCEPTION:
                    raise
                else:
                    errors[k] = e

        if errors:
            # TODO: messaging could be improved here
            raise ExceptionGroup("not all futures returned a result", [*errors.values()])

        return results


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
        self.__hosts = [
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
            self.__hosts.extend(
                [HostInfo(connection_info, shard_num=None, replica_num=None) for connection_info in extra_hosts]
            )
        self.__pools: dict[HostInfo, ChPool] = {}

    def __get_pool(self, host: HostInfo) -> ChPool:
        pool = self.__pools.get(host)
        if pool is None:
            pool = self.__pools[host] = make_ch_pool(host=host.connection_info.address, port=host.connection_info.port)
        return pool

    def map_hosts(self, fn: Callable[[Client], T]) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable once for each host in the cluster.
        """

        def task(pool):
            with pool.get_client() as client:
                return fn(client)

        with ThreadPoolExecutor() as executor:
            return FuturesMap({host: executor.submit(task, self.__get_pool(host)) for host in self.__hosts})

    def map_shards(self, fn: Callable[[Client], T]) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable once for each shard in the cluster.
        """

        def task(pool):
            with pool.get_client() as client:
                return fn(client)

        shard_hosts: dict[int, HostInfo] = {}
        for host in self.__hosts:
            if host.shard_num is not None and host.shard_num not in shard_hosts:
                shard_hosts[host.shard_num] = host

        with ThreadPoolExecutor() as executor:
            return FuturesMap({host: executor.submit(task, self.__get_pool(host)) for host in shard_hosts.values()})
