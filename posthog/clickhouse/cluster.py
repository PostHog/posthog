from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import (
    ALL_COMPLETED,
    FIRST_EXCEPTION,
    Future,
    ThreadPoolExecutor,
    as_completed,
)
from copy import copy
from typing import Literal, NamedTuple, TypeVar

from clickhouse_driver import Client
from clickhouse_pool import ChPool
from django.conf import settings

from posthog.clickhouse.client.connection import _make_ch_pool, default_client
from posthog.settings import CLICKHOUSE_PER_TEAM_SETTINGS


K = TypeVar("K")
V = TypeVar("V")


class FuturesMap(dict[K, Future[V]]):
    def __or__(self, other: FuturesMap[K, V]) -> FuturesMap[K, V]:
        # this method is needed as __or__ otherwise returns a plain dict
        if not isinstance(other, FuturesMap):
            return NotImplemented
        return FuturesMap(self | other)

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

    def make_pool(self, client_settings: Mapping[str, str] | None = None) -> ChPool:
        return _make_ch_pool(host=self.address, settings=client_settings)


class HostInfo(NamedTuple):
    connection_info: ConnectionInfo
    shard_num: int | None
    replica_num: int | None


T = TypeVar("T")


class ClickhouseCluster:
    def __init__(
        self,
        bootstrap_client: Client,
        extra_hosts: Sequence[ConnectionInfo] | None = None,
        logger: logging.Logger | None = None,
        client_settings: Mapping[str, str] | None = None,
    ) -> None:
        if logger is None:
            logger = logging.getLogger(__name__)

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
        self.__logger = logger
        self.__client_settings = client_settings

    def __get_task_function(self, host: HostInfo, fn: Callable[[Client], T]) -> Callable[[], T]:
        pool = self.__pools.get(host)
        if pool is None:
            pool = self.__pools[host] = host.connection_info.make_pool(self.__client_settings)

        def task():
            with pool.get_client() as client:
                self.__logger.debug("Executing %r on %r...", fn, host)
                try:
                    result = fn(client)
                except Exception:
                    self.__logger.debug("Failed to execute %r on %r!", fn, host, exc_info=True)
                    raise
                else:
                    self.__logger.debug("Successfully executed %r on %r.", fn, host)
                return result

        return task

    def any_host(self, fn: Callable[[Client], T]) -> Future[T]:
        with ThreadPoolExecutor() as executor:
            host = self.__hosts[0]
            return executor.submit(self.__get_task_function(host, fn))

    def map_all_hosts(self, fn: Callable[[Client], T]) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable once for each host in the cluster.
        """
        with ThreadPoolExecutor() as executor:
            return FuturesMap({host: executor.submit(self.__get_task_function(host, fn)) for host in self.__hosts})

    def map_all_hosts_in_shard(self, shard_num: int, fn: Callable[[Client], T]) -> FuturesMap[HostInfo, T]:
        with ThreadPoolExecutor() as executor:
            return FuturesMap(
                {
                    host: executor.submit(self.__get_task_function(host, fn))
                    for host in self.__hosts
                    if host.shard_num == shard_num
                }
            )

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


def get_cluster(
    logger: logging.Logger | None = None, client_settings: Mapping[str, str] | None = None
) -> ClickhouseCluster:
    extra_hosts = []
    for host_config in map(copy, CLICKHOUSE_PER_TEAM_SETTINGS.values()):
        extra_hosts.append(ConnectionInfo(host_config.pop("host")))
        assert len(host_config) == 0, f"unexpected values: {host_config!r}"
    return ClickhouseCluster(default_client(), extra_hosts=extra_hosts, logger=logger, client_settings=client_settings)
