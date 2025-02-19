from __future__ import annotations

from contextlib import contextmanager
import logging
import re
import time
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Set
from concurrent.futures import (
    ALL_COMPLETED,
    FIRST_EXCEPTION,
    Future,
    ThreadPoolExecutor,
    as_completed,
)
from copy import copy
from dataclasses import dataclass, field, replace
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
    shard_num: int | None = None
    replica_num: int | None = None
    host_cluster_type: str | None = None
    host_cluster_role: str | None = None


@dataclass(frozen=True)
class Host:
    info: HostInfo
    pool: ChPool = dataclass.field(hash=False)


@dataclass(frozen=True)
class Task(Generic[T]):
    fn: Callable[[Client], T]
    host: Host
    logger: logging.Logger

    def __call__(self) -> T:
        self.logger.info("Executing %r...", self)
        try:
            with self.host.pool.get_client() as client:
                result = self.fn(client)
        except Exception:
            self.logger.warn("Failed to execute %r!", self, exc_info=True)
            raise
        else:
            self.logger.info("Successfully executed %r.", self)
        return result


@dataclass(frozen=True)
class HostSet:
    hosts: Set[Host]
    executor: ThreadPoolExecutor = field(repr=False)
    logger: logging.getLogger

    def any(self, fn: Callable[[Client], T]) -> Future[T]:  # todo: find a way to augment with HostInfo?
        host = next(iter(self.hosts))
        return self.executor.submit(Task(fn, host, self.logger))

    def all(self, fn: Callable[[Client], T]) -> set[Future[T]]:  # todo: helper type to allow waiting on all at once
        return {self.executor.submit(Task(fn, host, self.logger)) for host in self.hosts}

    def filter(self, fn: Callable[[HostInfo], bool]) -> HostSet:
        # todo: handle node role filtering for convenience
        return replace(self, hosts={host for host in self.hosts if fn(host)})

    def group(self, fn: Callable[[HostInfo], K]) -> GroupedHostSet[K]:
        groups = defaultdict(set)
        for host in self.hosts:
            groups[fn(host)].append(host)
        return GroupedHostSet({key: replace(self, hosts=hosts) for key, hosts in groups.items()})

    @property
    def shards(self) -> GroupedHostSet[int]:
        return self.filter(lambda host: host.shard_num is not None).group(lambda host: host.shard_num)


@dataclass(frozen=True)
class GroupedHostSet(Generic[K]):
    groups: Mapping[K, HostSet]

    def any(self, fn: Callable[[Client], T]) -> Mapping[K, Future[T]]:
        return {key: hosts.any(fn) for key, hosts in self.groups.items()}

    def all(self, fn: Callable[[Client], T]) -> Mapping[K, set[Future[T]]]:
        return {key: hosts.all(fn) for key, hosts in self.groups.items()}

    def any_by_group(self, fns: Mapping[K, Callable[[Client], T]]) -> Mapping[K, Future[T]]:
        return {key: self.groups[key].any(fn) for key, fn in fns.items()}

    def all_by_group(self, fns: Mapping[K, Callable[[Client], T]]) -> Mapping[K, set[Future[T]]]:
        return {key: self.groups[key].all(fn) for key, fn in fns.items()}


class ClickhouseCluster:
    def __init__(
        self,
        host_infos: Set[HostInfo],
        logger: logging.Logger | None = None,
        client_settings: Mapping[str, str] | None = None,
    ) -> None:
        if logger is None:
            logger = logging.getLogger(__name__)

        self.__hosts = {Host(info, info.connection_info.make_pool(client_settings)) for info in host_infos}
        self.__logger = logger

    @contextmanager
    def __get_host_set(self, concurrency: int | None = None) -> Iterator[HostSet]:
        with ThreadPoolExecutor(concurrency) as executor:
            yield HostSet(self.__hosts, executor, self.__logger)

    def any_host_by_role(self, fn: Callable[[Client], T], node_role: NodeRole) -> Future[T]:
        """
        Execute the callable once for any host with the given node role.
        """
        with self.__get_host_set() as hosts:
            return hosts.filter(lambda host: host.host_cluster_role == node_role).any(fn)

    def map_all_hosts(self, fn: Callable[[Client], T], concurrency: int | None = None) -> set[Future[T]]:
        """
        Execute the callable once for each host in the cluster.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        with self.__get_host_set(concurrency) as hosts:
            return hosts.all(fn)

    def map_hosts_by_role(
        self,
        fn: Callable[[Client], T],
        node_role: NodeRole,
        concurrency: int | None = None,
    ) -> set[Future[T]]:
        """
        Execute the callable once for each host in the cluster with the given node role.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        with self.__get_host_set(concurrency) as hosts:
            return hosts.filter(lambda host: host.host_cluster_role == node_role).all(fn)

    def map_all_hosts_in_shard(
        self, shard_num: int, fn: Callable[[Client], T], concurrency: int | None = None
    ) -> set[Future[T]]:
        """
        Execute the callable once for each host in the specified shard.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        with self.__get_host_set(concurrency) as hosts:
            return hosts.filter(lambda host: host.shard_num == shard_num).all(fn)

    def map_all_hosts_in_shards(
        self, shard_fns: dict[int, Callable[[Client], T]], concurrency: int | None = None
    ) -> Mapping[int, set[Future[T]]]:
        """
        Execute the callable once for each host in the specified shards.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.

        Wait for all to return before returning upon ``.values()``
        """
        with self.__get_host_set(concurrency) as hosts:
            return hosts.shards.all_by_group(shard_fns)

    def map_any_host_in_shards(
        self, shard_fns: dict[int, Callable[[Client], T]], concurrency: int | None = None
    ) -> Mapping[int, Future[T]]:
        """
        Execute the callable on one host for each of the specified shards.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        with self.__get_host_set(concurrency) as hosts:
            return hosts.shards.any_by_group(shard_fns)

    def map_one_host_per_shard(
        self, fn: Callable[[Client], T], concurrency: int | None = None
    ) -> Mapping[int, Future[T]]:
        """
        Execute the callable once for each shard in the cluster.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        with self.__get_host_set(concurrency) as hosts:
            return hosts.shards.any(fn)


def get_cluster(
    logger: logging.Logger | None = None,
    client_settings: Mapping[str, str] | None = None,
    cluster: str = settings.CLICKHOUSE_CLUSTER,
) -> ClickhouseCluster:
    cluster_hosts = default_client().execute(
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
        {"name": cluster},
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

    for host_config in map(copy, CLICKHOUSE_PER_TEAM_SETTINGS.values()):
        connection_info = ConnectionInfo(host_config.pop("host"), None)
        assert len(host_config) == 0, f"unexpected values: {host_config!r}"
        host_info_set.add(HostInfo(connection_info))

    return ClickhouseCluster(host_info_set, logger=logger, client_settings=client_settings)


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
