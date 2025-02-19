from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence, Set
from concurrent.futures import (
    ALL_COMPLETED,
    FIRST_EXCEPTION,
    Future,
    ThreadPoolExecutor,
    as_completed,
)
from copy import copy
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, NamedTuple, TypeVar
from collections.abc import Iterable

from clickhouse_driver import Client
from clickhouse_pool import ChPool

from posthog import settings
from posthog.clickhouse.client.connection import NodeRole, _make_ch_pool, default_client
from posthog.settings import CLICKHOUSE_PER_TEAM_SETTINGS
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER


def ON_CLUSTER_CLAUSE(on_cluster=True):
    return f"ON CLUSTER '{CLICKHOUSE_CLUSTER}'" if on_cluster else ""


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
    port: int | None

    def make_pool(self, client_settings: Mapping[str, str] | None = None) -> ChPool:
        return _make_ch_pool(host=self.address, port=self.port, settings=client_settings)


T = TypeVar("T")
K = TypeVar("K")


class HostInfo(NamedTuple):
    connection_info: ConnectionInfo
    shard_num: int | None
    replica_num: int | None
    host_cluster_type: str | None
    host_cluster_role: str | None


@dataclass(frozen=True)
class Host:
    info: HostInfo
    pool: ChPool = dataclass.field(hash=False)

    def build_task(self, fn: Callable[[Client], T], logger: logging.Logger | None = None) -> Callable[[], T]:
        if logger is None:
            logger = logging.getLogger(__name__)

        def task():
            with self.pool.get_client() as client:
                logger.info("Executing %r on %r...", fn, self.info)
                try:
                    result = fn(client)
                except Exception:
                    logger.warn("Failed to execute %r on %r!", fn, self.info, exc_info=True)
                    raise
                else:
                    logger.info("Successfully executed %r on %r.", fn, self.info)
                return result

        return task


@dataclass(frozen=True)
class HostSet:
    executor: ThreadPoolExecutor
    hosts: Set[Host]

    def any(self, fn: Callable[[Client], T]) -> Future[T]:  # todo: find a way to augment with HostInfo?
        host = next(iter(self.hosts))
        return self.executor.submit(host.build_task(fn))

    def all(self, fn: Callable[[Client], T]) -> set[Future[T]]:  # todo: helper type to allow waiting on all at once
        # todo: ability to limit concurrency
        return {self.executor.submit(host.build_task(fn)) for host in self.hosts}

    def filter(self, fn: Callable[[HostInfo], bool]) -> HostSet:
        # todo: handle node role filtering for convenience
        return HostSet(self.executor, {host for host in self.hosts if fn(host)})

    def group(self, fn: Callable[[HostInfo], K]) -> HostGroup[K]:
        groups = defaultdict(set)
        for host in self.hosts:
            groups[fn(host)].append(host)
        return HostGroup({key: HostSet(self.executor, hosts) for key, hosts in groups.items()})

    @property
    def shards(self) -> HostGroup[int]:
        return self.filter(lambda host: host.shard_num is not None).group(lambda host: host.shard_num)


@dataclass(frozen=True)
class HostGroup(Generic[K]):
    groups: Mapping[K, HostSet]

    def any(self, fn: Callable[[Client], T]) -> Mapping[K, Future[T]]:
        return {key: hosts.any(fn) for key, hosts in self.groups.items()}

    def all(self, fn: Callable[[Client], T]) -> Mapping[K, set[Future[T]]]:
        # TODO: ability to limit concurrency
        return {key: hosts.all(fn) for key, hosts in self.groups.items()}

    def join_any(self, fns: Mapping[K, Callable[[Client], T]]) -> Mapping[K, Future[T]]:
        return {key: self.groups[key].any(fn) for key, fn in fns.items()}

    def join_all(self, fns: Mapping[K, Callable[[Client], T]]) -> Mapping[K, set[Future[T]]]:
        # TODO: ability to limit concurrency
        return {key: self.groups[key].all(fn) for key, fn in fns.items()}


class ClickhouseCluster:
    def __init__(
        self,
        bootstrap_client: Client,
        extra_hosts: Sequence[ConnectionInfo] | None = None,
        logger: logging.Logger | None = None,
        client_settings: Mapping[str, str] | None = None,
        cluster: str | None = None,
    ) -> None:
        if logger is None:
            logger = logging.getLogger(__name__)

        cluster_hosts = bootstrap_client.execute(
            """
            SELECT
                host_address,
                port,
                shard_num,
                replica_num,
                getMacro('hostClusterType') as host_cluster_type,
                getMacro('hostClusterRole') as host_cluster_role
            FROM clusterAllReplicas(%(name)s, system.clusters)
            WHERE name = %(name)s and is_local
            ORDER BY shard_num, replica_num
            """,
            {"name": cluster or settings.CLICKHOUSE_CLUSTER},
        )

        host_info_set = {
            HostInfo(
                ConnectionInfo(
                    host_address,
                    # We only use the port from system.clusters if we're running in E2E tests or debug mode,
                    # otherwise, we will use the default port.
                    port=port if (settings.E2E_TESTING or settings.DEBUG) else None,
                ),
                shard_num if host_cluster_role != "coordinator" else None,
                replica_num if host_cluster_role != "coordinator" else None,
                host_cluster_type,
                host_cluster_role,
            )
            for (host_address, port, shard_num, replica_num, host_cluster_type, host_cluster_role) in cluster_hosts
        }

        if extra_hosts is not None and len(extra_hosts) > 0:
            host_info_set.update(
                HostInfo(
                    connection_info,
                    shard_num=None,
                    replica_num=None,
                    host_cluster_type=None,
                    host_cluster_role=None,
                )
                for connection_info in extra_hosts
            )

        self.hosts = HostSet(
            ThreadPoolExecutor(),
            {Host(info, info.connection_info.make_pool(client_settings)) for info in host_info_set},
        )

    def any_host_by_role(self, fn: Callable[[Client], T], node_role: NodeRole) -> Future[T]:
        """
        Execute the callable once for any host with the given node role.
        """
        return self.hosts.filter(lambda host: host.host_cluster_role == node_role).any(fn)

    def map_all_hosts(self, fn: Callable[[Client], T], concurrency: int | None = None) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable once for each host in the cluster.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        return self.hosts.all(fn)

    def map_hosts_by_role(
        self,
        fn: Callable[[Client], T],
        node_role: NodeRole,
        concurrency: int | None = None,
    ) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable once for each host in the cluster with the given node role.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        return self.hosts.filter(lambda host: host.host_cluster_role == node_role).all(fn)

    def map_all_hosts_in_shard(
        self, shard_num: int, fn: Callable[[Client], T], concurrency: int | None = None
    ) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable once for each host in the specified shard.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        return self.hosts.filter(lambda host: host.shard_num == shard_num).all(fn)

    def map_all_hosts_in_shards(
        self, shard_fns: dict[int, Callable[[Client], T]], concurrency: int | None = None
    ) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable once for each host in the specified shards.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.

        Wait for all to return before returning upon ``.values()``
        """
        return self.hosts.shards.join_all(shard_fns)

    def map_any_host_in_shards(
        self, shard_fns: dict[int, Callable[[Client], T]], concurrency: int | None = None
    ) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable on one host for each of the specified shards.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        return self.hosts.shards.join_any(shard_fns)

    def map_one_host_per_shard(
        self, fn: Callable[[Client], T], concurrency: int | None = None
    ) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable once for each shard in the cluster.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        return self.hosts.shards.any(fn)


def get_cluster(
    logger: logging.Logger | None = None, client_settings: Mapping[str, str] | None = None, cluster: str | None = None
) -> ClickhouseCluster:
    extra_hosts = []
    for host_config in map(copy, CLICKHOUSE_PER_TEAM_SETTINGS.values()):
        extra_hosts.append(ConnectionInfo(host_config.pop("host"), None))
        assert len(host_config) == 0, f"unexpected values: {host_config!r}"
    return ClickhouseCluster(
        default_client(), extra_hosts=extra_hosts, logger=logger, client_settings=client_settings, cluster=cluster
    )


@dataclass
class Query:
    query: str
    parameters: Any | None = None

    def __call__(self, client: Client):
        return client.execute(self.query, self.parameters)


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
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if invalid_keys := {key for key in self.parameters.keys() if key.startswith("__")}:
            raise ValueError(f"invalid parameter names: {invalid_keys!r} (keys cannot start with double underscore)")

    def find(self, client: Client) -> Mutation | None:
        """Find the running mutation task, if one exists."""

        if self.is_lightweight_delete:
            command = self.__convert_lightweight_delete_to_mutation_command()
        else:
            command = self.command

        if (command_kind_match := re.match(r"^(\w+) ", command.lstrip())) is None:
            raise ValueError(f"could not determine command kind from {command!r}")

        results = client.execute(
            f"""
            SELECT mutation_id
            FROM system.mutations
            WHERE
                database = %(__database)s
                AND table = %(__table)s
                -- only one command per mutation is currently supported, so throw if the mutation contains more than we expect to find
                -- throwIf always returns 0 if it does not throw, so negation turns this condition into effectively a noop if the test passes
                AND NOT throwIf(
                    length(splitByString(%(__command_kind)s, replaceRegexpAll(replaceRegexpAll(replaceRegexpAll(formatQuery($__sql$ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{self.table} {command}$__sql$), '\\s+', ' '), '\\(\\s+', '('), '\\s+\\)', ')')) as lines) != 2,
                    'unexpected number of lines, expected 2 (ALTER TABLE prefix, followed by single command)'
                )
                AND command = %(__command_kind)s || ' ' || trim(lines[2])
                AND NOT is_killed  -- ok to restart a killed mutation
            ORDER BY create_time DESC
            """,
            {
                f"__database": settings.CLICKHOUSE_DATABASE,
                f"__table": self.table,
                f"__command_kind": command_kind_match.group(1),
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
        """Enqueue the mutation (or return the existing mutation if it is already running or has run.)"""
        if task := self.find(client):
            return task

        if self.is_lightweight_delete:
            client.execute(self.command, self.parameters, settings=self.settings)

        else:
            client.execute(
                f"ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{self.table} {self.command}",
                self.parameters,
                settings=self.settings,
            )

        # mutations are not always immediately visible, so give it a bit of time to show up
        start = time.time()
        for _ in range(5):
            if task := self.find(client):
                return task
            time.sleep(1.0)

        raise Exception(f"unable to find mutation after {time.time()-start:0.2f}s!")

    @property
    def is_lightweight_delete(self) -> bool:
        return re.match(r"(?i)^DELETE\s+FROM\s+.*", self.command.strip()) is not None

    def __convert_lightweight_delete_to_mutation_command(self) -> str:
        match = re.match(r"(?i)^DELETE\s+FROM\s+(?:\w+\.)*\w+\s+WHERE\s+", self.command.strip())
        if not match:
            raise ValueError(f"Invalid DELETE command format: {self.command}")
        where_clause = self.command.strip()[match.end() :]
        return f"UPDATE _row_exists = 0 WHERE {where_clause}"

    def run_on_shards(self, cluster: ClickhouseCluster, shards: Iterable[int] | None = None) -> None:
        """
        Enqueue (or find) this mutation on one host in each shard, and then block until the mutation is complete on all
        hosts within the affected shards.
        """
        if shards is not None:
            shard_host_mutations = cluster.map_any_host_in_shards({shard: self.enqueue for shard in shards})
        else:
            shard_host_mutations = cluster.map_one_host_per_shard(self.enqueue)

        # XXX: need to convert the `shard_num` of type `int | None` to `int` to appease the type checker -- but nothing
        # should have actually been filtered out, since we're using the cluster shard functions for targeting
        shard_mutations = {
            host.shard_num: mutations
            for host, mutations in shard_host_mutations.result().items()
            if host.shard_num is not None
        }
        assert len(shard_mutations) == len(shard_host_mutations)

        cluster.map_all_hosts_in_shards(
            {shard_num: mutation.wait for shard_num, mutation in shard_mutations.items()}
        ).result()
