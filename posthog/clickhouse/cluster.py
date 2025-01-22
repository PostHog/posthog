from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ALL_COMPLETED, FIRST_EXCEPTION, Future, ThreadPoolExecutor, as_completed
from typing import Literal, NamedTuple, TypeVar

from clickhouse_driver import Client
from clickhouse_pool import ChPool
from django.conf import settings

from posthog.clickhouse.client.connection import make_ch_pool


logger = logging.getLogger(__name__)


K = TypeVar("K")
V = TypeVar("V")


class FuturesMap(dict[K, Future[V]]):
    def as_completed(self, timeout: float | int | None = None) -> Iterator[tuple[K, Future[V]]]:
        reverse_map = {v: k for k, v in self.items()}
        assert len(reverse_map) == len(self)

        for f in as_completed(self.values(), timeout=timeout):
            yield reverse_map[f], f

    def result(
        self,
        timeout: float | int | None = None,
        return_when: Literal["FIRST_EXCEPTION", "ALL_COMPLETED"] = ALL_COMPLETED,
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

    def make_pool(self) -> ChPool:
        return make_ch_pool(host=self.address)


class HostInfo(NamedTuple):
    connection_info: ConnectionInfo
    shard_num: int | None
    replica_num: int | None


T = TypeVar("T")


class ClickhouseCluster:
    def __init__(self, bootstrap_client: Client, extra_hosts: Sequence[ConnectionInfo] | None = None) -> None:
        self.__hosts = [
            HostInfo(ConnectionInfo(host_address), shard_num, replica_num)
            for (host_address, shard_num, replica_num) in bootstrap_client.execute(
                """
                SELECT host_address, shard_num, replica_num
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

    def __get_task_function(self, host: HostInfo, fn: Callable[[Client], T]) -> Callable[[], T]:
        pool = self.__pools.get(host)
        if pool is None:
            pool = self.__pools[host] = host.connection_info.make_pool()

        def task():
            with pool.get_client() as client:
                logger.debug("Executing %r on %r...", fn, host)
                try:
                    result = fn(client)
                except Exception:
                    logger.exception("Failed to execute %r on %r!", fn, host)
                    raise
                else:
                    logger.debug("Successfully executed %r on %r.", fn, host)
                return result

        return task

    def map_all_hosts(self, fn: Callable[[Client], T]) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable once for each host in the cluster.
        """
        with ThreadPoolExecutor() as executor:
            return FuturesMap({host: executor.submit(self.__get_task_function(host, fn)) for host in self.__hosts})

    def map_one_host_per_shard(self, fn: Callable[[Client], T]) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable once for each shard in the cluster.
        """
        shard_hosts: dict[int, HostInfo] = {}
        for host in self.__hosts:
            if host.shard_num is not None and host.shard_num not in shard_hosts:
                shard_hosts[host.shard_num] = host

        with ThreadPoolExecutor() as executor:
            return FuturesMap(
                {host: executor.submit(self.__get_task_function(host, fn)) for host in shard_hosts.values()}
            )
