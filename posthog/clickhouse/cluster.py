from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import (
    ALL_COMPLETED,
    FIRST_EXCEPTION,
    Future,
    ThreadPoolExecutor,
    as_completed,
)
from copy import copy
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple, TypeVar

from clickhouse_driver import Client
from clickhouse_pool import ChPool

from posthog import settings
from posthog.clickhouse.client.connection import _make_ch_pool, default_client
from posthog.settings import CLICKHOUSE_PER_TEAM_SETTINGS

K = TypeVar("K")
V = TypeVar("V")


class FuturesMap(dict[K, Future[V]]):
    def as_completed(self, timeout: float | int | None = None) -> Iterator[tuple[K, Future[V]]]:
        reverse_map = {v: k for k, v in self.items()}
        assert len(reverse_map) == len(self)

        for f in as_completed(self.values(), timeout=timeout):
            yield reverse_map[f], f

    def merge(self, other: FuturesMap[K, V]) -> FuturesMap[K, V]:
        return FuturesMap(self | other)

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


@dataclass
class Mutation:
    table: str
    mutation_id: str

    def is_done(self, client: Client) -> bool:
        [[is_done]] = client.execute(
            f"""
            SELECT is_done
            FROM system.mutations
            WHERE database = %(database)s AND table = %(table)s AND mutation_id = %(mutation_id)s
            ORDER BY create_time DESC
            """,
            {"database": settings.CLICKHOUSE_DATABASE, "table": self.table, "mutation_id": self.mutation_id},
        )
        return is_done

    def wait(self, client: Client) -> None:
        while not self.is_done(client):
            time.sleep(15.0)


@dataclass
class MutationRunner:
    table: str
    command: str  # the part after ALTER TABLE prefix, i.e. UPDATE, DELETE, MATERIALIZE, etc.
    parameters: Mapping[str, Any]

    def find(self, client: Client) -> Mutation | None:
        """Find the running mutation task, if one exists."""
        results = client.execute(
            f"""
            SELECT mutation_id
            FROM system.mutations
            WHERE
                database = %(_database_{id(self)})s
                AND table = %(_table_{id(self)})s
                -- only one command per mutation is currently supported, so throw if the mutation contains more than we expect to find
                -- throwIf always returns 0 if it does not throw, so negation turns this condition into effectively a noop if the test passes
                AND NOT throwIf(
                    length(splitByChar('\n', formatQuery($_sql_{id(self)}$ALTER TABLE {settings.CLICKHOUSE_DATABASE}{self.table} {self.command}$_sql_{id(self)}$)) as lines) != 2,
                    'unexpected number of lines, expected 2 (ALTER TABLE prefix, followed by single command)'
                )
                AND command = trim(lines[2])
                AND NOT is_killed  -- ok to restart a killed mutation
            ORDER BY create_time DESC
            """,
            {
                f"_database_{id(self)}": settings.CLICKHOUSE_DATABASE,
                f"_table_{id(self)}": self.table,
                **self.parameters,
            },
        )
        if not results:
            return None
        else:
            assert len(results) == 1
            [[mutation_id]] = results
            return Mutation(self.table, mutation_id)

    def enqueue(self, client: Client) -> Mutation:
        """Enqueue the mutation (or return the existing mutation if it is already running.)"""
        if task := self.find(client):
            return task

        client.execute(
            f"ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{self.table} {self.command}",
            self.parameters,
        )

        task = self.find(client)
        assert task is not None

        return task
