from __future__ import annotations

import abc
import time
import logging
import itertools
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence, Set
from concurrent.futures import ALL_COMPLETED, FIRST_EXCEPTION, Future, ThreadPoolExecutor, as_completed
from copy import copy
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, NamedTuple, Optional, TypeVar

import dagster
from clickhouse_driver import Client
from clickhouse_pool import ChPool

from posthog import settings
from posthog.clickhouse.client.connection import NodeRole, Workload, _make_ch_pool, default_client
from posthog.settings import CLICKHOUSE_PER_TEAM_SETTINGS
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER

logger = dagster.get_dagster_logger("clickhouse")


def ON_CLUSTER_CLAUSE(on_cluster=True):
    return f"ON CLUSTER '{CLICKHOUSE_CLUSTER}'" if on_cluster else ""


K = TypeVar("K")
V = TypeVar("V")


def format_exception_summary(e: Exception, max_length: int = 256) -> str:
    value = repr(e).splitlines()[0]
    if len(value) > max_length:
        value = value[:max_length] + "..."
    return value


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
            raise ExceptionGroup(
                f"{len(errors)} future(s) did not return a result:\n\n"
                + "\n".join([f"* {key}: {format_exception_summary(e)}" for key, e in errors.items()]),
                [*errors.values()],
            )

        return results


class ConnectionInfo(NamedTuple):
    host: str
    port: int | None

    def make_pool(self, client_settings: Mapping[str, str] | None = None) -> ChPool:
        return _make_ch_pool(host=self.host, port=self.port, settings=client_settings)


class HostInfo(NamedTuple):
    connection_info: ConnectionInfo
    shard_num: int | None
    replica_num: int | None
    host_cluster_type: str | None
    host_cluster_role: str | None


T = TypeVar("T")


class ClickhouseCluster:
    def __init__(
        self,
        bootstrap_client: Client,
        extra_hosts: Sequence[ConnectionInfo] | None = None,
        logger: logging.Logger | None = None,
        client_settings: Mapping[str, str] | None = None,
        cluster: str | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        if logger is None:
            logger = logging.getLogger(__name__)

        self.__shards: dict[int, set[HostInfo]] = defaultdict(set)
        self.__extra_hosts: set[HostInfo] = set()

        cluster_hosts = self.__get_cluster_hosts(bootstrap_client, cluster or settings.CLICKHOUSE_CLUSTER, retry_policy)

        for row in cluster_hosts:
            (host_name, port, shard_num, replica_num, host_cluster_type, host_cluster_role) = row
            host_info = HostInfo(
                ConnectionInfo(
                    host_name,
                    # We only use the port from system.clusters if we're running in E2E tests or debug mode,
                    # otherwise, we will use the default port.
                    port=port if (settings.E2E_TESTING or settings.DEBUG) else None,
                ),
                shard_num if host_cluster_role == NodeRole.DATA else None,
                replica_num if host_cluster_role == NodeRole.DATA else None,
                host_cluster_type,
                host_cluster_role,
            )
            (self.__shards[shard_num] if host_info.shard_num is not None else self.__extra_hosts).add(host_info)

        if extra_hosts is not None and len(extra_hosts) > 0:
            self.__extra_hosts.update(
                [
                    HostInfo(
                        connection_info,
                        shard_num=None,
                        replica_num=None,
                        host_cluster_type=None,
                        host_cluster_role=None,
                    )
                    for connection_info in extra_hosts
                ]
            )

        self.__pools: dict[HostInfo, ChPool] = {}
        self.__logger = logger
        self.__client_settings = client_settings
        self.__retry_policy = retry_policy

    def __get_cluster_hosts(self, client: Client, cluster: str, retry_policy: RetryPolicy | None = None):
        get_cluster_hosts_fn = lambda client: client.execute(
            """
            SELECT host_name, port, shard_num, replica_num, getMacro('hostClusterType') as host_cluster_type, getMacro('hostClusterRole') as host_cluster_role
            FROM clusterAllReplicas(%(name)s, system.clusters)
            WHERE name = %(name)s and is_local
            ORDER BY shard_num, replica_num
            """,
            {"name": cluster},
        )

        if retry_policy is not None:
            get_cluster_hosts_fn = retry_policy(get_cluster_hosts_fn)

        return get_cluster_hosts_fn(client)

    def __get_task_function(self, host: HostInfo, fn: Callable[[Client], T]) -> Callable[[], T]:
        pool = self.__pools.get(host)
        if pool is None:
            pool = self.__pools[host] = host.connection_info.make_pool(self.__client_settings)

        if self.__retry_policy is not None:
            fn = self.__retry_policy(fn)

        def task():
            with pool.get_client() as client:
                self.__logger.info("Executing %r on %r...", fn, host)
                try:
                    result = fn(client)
                except Exception as e:
                    self.__logger.warn("Failed to execute %r on %r: %s", fn, host, e, exc_info=True)
                    raise
                else:
                    self.__logger.info("Successfully executed %r on %r.", fn, host)
                return result

        return task

    def __hosts_by_roles(
        self, hosts: set[HostInfo], node_roles: list[NodeRole], workload: Workload = Workload.DEFAULT
    ) -> set[HostInfo]:
        return {
            host
            for host in hosts
            if (host.host_cluster_role in node_roles or NodeRole.ALL in node_roles)
            and (host.host_cluster_type == workload.value.lower() or workload == Workload.DEFAULT)
        }

    @property
    def __hosts(self) -> set[HostInfo]:
        """Set containing all hosts in the cluster."""
        hosts = set(self.__extra_hosts)
        for shard_hosts in self.__shards.values():
            hosts.update(shard_hosts)
        return hosts

    @property
    def shards(self) -> list[int]:
        return list(self.__shards.keys())

    def any_host(self, fn: Callable[[Client], T]) -> Future[T]:
        with ThreadPoolExecutor() as executor:
            host = next(iter(self.__hosts))
            return executor.submit(self.__get_task_function(host, fn))

    def any_host_by_role(
        self, fn: Callable[[Client], T], node_role: NodeRole, workload: Workload = Workload.DEFAULT
    ) -> Future[T]:
        """
        Execute the callable once for any host with the given node role.
        """
        return self.any_host_by_roles(fn, [node_role], workload)

    def any_host_by_roles(
        self, fn: Callable[[Client], T], node_roles: list[NodeRole], workload: Workload = Workload.DEFAULT
    ) -> Future[T]:
        """
        Execute the callable once for any host with the given node role.
        """
        with ThreadPoolExecutor() as executor:
            try:
                host = next(iter(self.__hosts_by_roles(self.__hosts, node_roles, workload)))
            except StopIteration:
                raise ValueError(f"No hosts found with roles {node_roles}")
            return executor.submit(self.__get_task_function(host, fn))

    def map_all_hosts(self, fn: Callable[[Client], T], concurrency: int | None = None) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable once for each host in the cluster.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        return self.map_hosts_by_role(fn, NodeRole.ALL, concurrency)

    def map_hosts_by_role(
        self,
        fn: Callable[[Client], T],
        node_role: NodeRole,
        concurrency: int | None = None,
        workload: Workload = Workload.DEFAULT,
    ) -> FuturesMap[HostInfo, T]:
        return self.map_hosts_by_roles(fn, [node_role], concurrency, workload)

    def map_hosts_by_roles(
        self,
        fn: Callable[[Client], T],
        node_roles: list[NodeRole],
        concurrency: int | None = None,
        workload: Workload = Workload.DEFAULT,
    ) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable once for each host in the cluster with the given node role.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            return FuturesMap(
                {
                    host: executor.submit(self.__get_task_function(host, fn))
                    for host in self.__hosts_by_roles(self.__hosts, node_roles, workload)
                }
            )

    def map_all_hosts_in_shard(
        self, shard_num: int, fn: Callable[[Client], T], concurrency: int | None = None
    ) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable once for each host in the specified shard.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        return self.map_hosts_in_shard_by_role(shard_num, fn, concurrency, NodeRole.ALL, Workload.DEFAULT)

    def map_hosts_in_shard_by_role(
        self,
        shard_num: int,
        fn: Callable[[Client], T],
        concurrency: int | None = None,
        node_role: NodeRole = NodeRole.ALL,
        workload: Workload = Workload.DEFAULT,
    ) -> FuturesMap[HostInfo, T]:
        return self.map_hosts_in_shard_by_roles(shard_num, fn, [node_role], concurrency, workload)

    def map_hosts_in_shard_by_roles(
        self,
        shard_num: int,
        fn: Callable[[Client], T],
        node_roles: list[NodeRole],
        concurrency: int | None = None,
        workload: Workload = Workload.DEFAULT,
    ) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable once for each host in the specified shard and role.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            return FuturesMap(
                {
                    host: executor.submit(self.__get_task_function(host, fn))
                    for host in self.__hosts_by_roles(self.__shards[shard_num], node_roles, workload)
                }
            )

    def map_all_hosts_in_shards(
        self,
        shard_fns: dict[int, Callable[[Client], T]],
        concurrency: int | None = None,
    ) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable once for each host in the specified shards.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.

        Wait for all to return before returning upon ``.values()``
        """
        shard_host_fn = {}
        for shard, fn in shard_fns.items():
            for host in self.__shards[shard]:
                shard_host_fn[host] = fn

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            return FuturesMap(
                {host: executor.submit(self.__get_task_function(host, fn)) for host, fn in shard_host_fn.items()}
            )

    def map_any_host_in_shards(
        self, shard_fns: dict[int, Callable[[Client], T]], concurrency: int | None = None
    ) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable on one host for each of the specified shards.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        return self.map_any_host_in_shards_by_role(
            shard_fns,
            concurrency=concurrency,
            node_role=NodeRole.ALL,
            workload=Workload.DEFAULT,
        )

    def map_any_host_in_shards_by_role(
        self,
        shard_fns: dict[int, Callable[[Client], T]],
        concurrency: int | None = None,
        node_role: NodeRole = NodeRole.ALL,
        workload: Workload = Workload.DEFAULT,
    ) -> FuturesMap[HostInfo, T]:
        return self.map_any_host_in_shards_by_roles(
            shard_fns, node_roles=[node_role], concurrency=concurrency, workload=workload
        )

    def map_any_host_in_shards_by_roles(
        self,
        shard_fns: dict[int, Callable[[Client], T]],
        node_roles: list[NodeRole],
        concurrency: int | None = None,
        workload: Workload = Workload.DEFAULT,
    ) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable on one host for each of the specified shards and role.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        shard_host_fns = {}
        for shard, fn in shard_fns.items():
            try:
                host = next(iter(self.__hosts_by_roles(self.__shards[shard], node_roles, workload)))
                shard_host_fns[host] = fn
            except StopIteration:
                raise ValueError(
                    f"No hosts found with role {node_roles} and workload {workload.value} in shard {shard}"
                )

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            return FuturesMap(
                {host: executor.submit(self.__get_task_function(host, fn)) for host, fn in shard_host_fns.items()}
            )

    def map_one_host_per_shard(
        self, fn: Callable[[Client], T], concurrency: int | None = None
    ) -> FuturesMap[HostInfo, T]:
        """
        Execute the callable once for each shard in the cluster.

        The number of concurrent queries can limited with the ``concurrency`` parameter, or set to ``None`` to use the
        default limit of the executor.
        """
        hosts = {next(iter(shard_hosts)) for shard_hosts in self.__shards.values()}
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            return FuturesMap({host: executor.submit(self.__get_task_function(host, fn)) for host in hosts})


def get_cluster(
    logger: logging.Logger | None = None,
    client_settings: Mapping[str, str] | None = None,
    cluster: str | None = None,
    retry_policy: RetryPolicy | None = None,
    host: str = settings.CLICKHOUSE_HOST,
) -> ClickhouseCluster:
    extra_hosts = []
    for host_config in map(copy, CLICKHOUSE_PER_TEAM_SETTINGS.values()):
        extra_hosts.append(ConnectionInfo(host_config.pop("host"), None))
        assert len(host_config) == 0, f"unexpected values: {host_config!r}"
    return ClickhouseCluster(
        default_client(host=host),
        extra_hosts=extra_hosts,
        logger=logger,
        client_settings=client_settings,
        cluster=cluster,
        retry_policy=retry_policy,
    )


@dataclass
class Query:
    query: str
    parameters: Any | None = None
    settings: dict[str, str] | None = None

    def __call__(self, client: Client):
        return client.execute(self.query, self.parameters, settings=self.settings)

    def __repr__(self) -> str:
        if self.parameters and isinstance(self.parameters, list):
            params_repr = f"{self.parameters[:50]!r} (showing first 50 out of {len(self.parameters)} parameters)"
        else:
            params_repr = f"{self.parameters!r}"
        return f"Query(query={self.query!r}, parameters={params_repr}, settings={self.settings!r})"


@dataclass
class ExponentialBackoff:
    delay: float
    max_delay: Optional[float] = None
    exp: float = 2.0

    def __call__(self, attempt: int) -> float:
        delay = self.delay * (attempt**self.exp)
        return min(delay, self.max_delay) if self.max_delay is not None else delay


@dataclass
class RetryPolicy:
    max_attempts: int
    delay: float | Callable[[int], float]
    exceptions: tuple[type[Exception], ...] | Callable[[Exception], bool] = (Exception,)

    def __call__(self, fn: Callable[[Client], T]) -> Retryable[T]:
        return Retryable(fn, self)


@dataclass
class Retryable(Generic[T]):  # note: this class exists primarily to allow a readable __repr__
    callable: Callable[[Client], T]
    policy: RetryPolicy

    def __call__(self, client: Client) -> T:
        if isinstance(self.policy.exceptions, tuple):
            is_retryable_exception = lambda e: isinstance(e, self.policy.exceptions)
        else:
            is_retryable_exception = self.policy.exceptions

        if not callable(self.policy.delay):

            def delay_fn(_):
                return self.policy.delay
        else:
            delay_fn = self.policy.delay

        counter = itertools.count(1)
        while (attempt := next(counter)) <= self.policy.max_attempts:
            try:
                return self.callable(client)
            except Exception as e:
                if is_retryable_exception(e) and attempt < self.policy.max_attempts:
                    delay = delay_fn(attempt)
                    logger.warning(
                        "Failed to execute %r (attempt #%s, retry in %0.2fs): %s", self.callable, attempt, delay, e
                    )
                    time.sleep(delay)
                else:
                    raise

        raise RuntimeError("unexpected fallthrough")


class MutationNotFound(Exception):
    pass


@dataclass
class MutationWaiter:
    table: str
    mutation_ids: Set[str]

    def __call__(self, client: Client) -> None:
        return self.wait(client)

    def is_done(self, client: Client) -> bool:
        # TODO: this should maybe raise if the number of commands per mutation is incorrect?
        rows = client.execute(
            f"""
            SELECT
                mutation_id,  -- ensure no rows are returned if the mutation we're looking for doesn't exist
                countIf(is_done) = count() as all_commands_done -- multiple commands can be issued in a single mutation, consolidate all statuses into one value
            FROM system.mutations
            WHERE database = %(database)s AND table = %(table)s AND mutation_id IN %(mutation_ids)s
            GROUP BY ALL
            """,
            {"database": settings.CLICKHOUSE_DATABASE, "table": self.table, "mutation_ids": list(self.mutation_ids)},
        )

        statuses = dict(rows)
        assert len(rows) == len(statuses)

        if missing_mutations := (self.mutation_ids - statuses.keys()):
            raise MutationNotFound(f"could not find mutation(s): {missing_mutations!r}")
        elif unexpected_mutations := (statuses.keys() - self.mutation_ids):
            raise ValueError(f"received unexpected mutation(s): {unexpected_mutations!r}")  # should never happen
        else:
            return all(statuses.values())

    def wait(self, client: Client) -> None:
        while not self.is_done(client):
            time.sleep(15.0)


@dataclass
class MutationRunner(abc.ABC):
    table: str
    parameters: Mapping[str, Any] = field(default_factory=dict, kw_only=True)
    settings: Mapping[str, Any] = field(default_factory=dict, kw_only=True)
    force: bool = field(default=False, kw_only=True)  # whether to force the mutation to run even if it already exists

    @abc.abstractmethod
    def get_all_commands(self) -> Set[str]:
        """Returns all of the commands that are considered part of this mutation."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_statement(self, commands: Set[str]) -> str:
        """Returns a statement that can be used to enqueue a mutation for the provided commands."""
        raise NotImplementedError

    def __post_init__(self) -> None:
        if invalid_keys := {key for key in self.parameters.keys() if key.startswith("__")}:
            raise ValueError(f"invalid parameter names: {invalid_keys!r} (keys cannot start with double underscore)")

    def __call__(self, client: Client) -> MutationWaiter:
        """
        Ensure that all mutation commands are either running, or have previously run to completion. Returns an object
        that can be used to check the status of the mutation and wait for it to be finished.
        """
        expected_commands = self.get_all_commands()
        if self.force:
            logger.info(
                "Forcing mutation for %r, even if it already exists. This may cause issues if the mutation is already running.",
                expected_commands,
            )
            mutations_running: Mapping[str, str] = {}
        else:
            logger.info("Ensuring mutation for %r is running or has completed.", expected_commands)
            mutations_running = self.find_existing_mutations(client, expected_commands)

        commands_to_enqueue = expected_commands - mutations_running.keys()
        if not commands_to_enqueue:
            return MutationWaiter(self.table, set(mutations_running.values()))

        client.execute(self.get_statement(commands_to_enqueue), self.parameters, settings=self.settings)

        # mutations are not always immediately visible, so give anything new a bit of time to show up
        start = time.time()
        for _ in range(5):
            mutations_running = self.find_existing_mutations(client, expected_commands)
            if mutations_running.keys() == expected_commands:
                return MutationWaiter(self.table, set(mutations_running.values()))
            time.sleep(1.0)

        raise Exception(
            f"unable to find mutation for {expected_commands - mutations_running.keys()!r} after {time.time() - start:0.2f}s!"
        )

    def find_existing_mutations(self, client: Client, commands: Set[str] | None = None) -> Mapping[str, str]:
        """
        Find the mutation ID (if it exists) associated with each command provided (or all commands if no commands are
        specified.)
        """
        if commands is None:
            commands = self.get_all_commands()

        if unexpected_commands := (commands - self.get_all_commands()):
            raise ValueError(f"unexpected commands: {unexpected_commands!r}")

        # we match commands by position, so require a stable ordering - this is because this class is provided the
        # command template without parameter values, while the record in the mutation log will have the values inlined
        command_list = [*commands]
        mutations = client.execute(
            f"""
            SELECT mutation_id
            FROM (
                SELECT
                    (arrayJoin(
                        arrayZip(
                            arrayMap(
                                command -> extract(command, '^\\s*(.*?)(?:,)?\\s*$'),  -- strip leading/trailing whitespace and optional trailing comma
                                arraySlice(  -- drop "ALTER TABLE" preamble line
                                    splitByChar('\n', formatQuery($__sql$ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{self.table} {", ".join(command_list)}$__sql$)),
                                    2
                                )
                            ) as commands,
                            arrayEnumerate(commands)
                        )
                    ) as t).1 as command,
                    t.2 as position
            ) commands
            LEFT OUTER JOIN (
                SELECT
                    command,
                    argMax(mutation_id, create_time) as mutation_id  -- Get the most recent mutation for each command
                FROM system.mutations
                WHERE
                    database = %(__database)s
                    AND table = %(__table)s
                    AND NOT is_killed  -- ok to restart a killed mutation
                GROUP BY command
            ) mutations USING (command)
            ORDER BY position ASC
            SETTINGS join_use_nulls = 1
            """,
            {
                f"__database": settings.CLICKHOUSE_DATABASE,
                f"__table": self.table,
                **self.parameters,
            },
        )
        assert len(mutations) == len(command_list)
        return {
            command: mutation_id for command, (mutation_id,) in zip(command_list, mutations) if mutation_id is not None
        }

    def run_on_shards(self, cluster: ClickhouseCluster, shards: Iterable[int] | None = None) -> None:
        """
        Enqueue (or find) this mutation on one host in each shard, and then block until the mutation is complete on all
        hosts within the affected shards.
        """
        if shards is not None:
            shard_host_mutation_waiters = cluster.map_any_host_in_shards({shard: self for shard in shards})
        else:
            shard_host_mutation_waiters = cluster.map_one_host_per_shard(self)

        # XXX: need to convert the `shard_num` of type `int | None` to `int` to appease the type checker -- but nothing
        # should have actually been filtered out, since we're using the cluster shard functions for targeting
        shard_mutations = {
            host.shard_num: mutations
            for host, mutations in shard_host_mutation_waiters.result().items()
            if host.shard_num is not None
        }
        assert len(shard_mutations) == len(shard_host_mutation_waiters)

        # during periods of elevated replication lag, it may take some time for mutations to become available on
        # the shards, so give them a little bit of breathing room with retries
        retry_policy = RetryPolicy(max_attempts=3, delay=10.0, exceptions=(MutationNotFound,))
        cluster.map_all_hosts_in_shards(
            {shard_num: retry_policy(waiter) for shard_num, waiter in shard_mutations.items()}
        ).result()


@dataclass
class AlterTableMutationRunner(MutationRunner):
    commands: Set[str] = field(
        kw_only=True
    )  # the part after ALTER TABLE prefix, i.e. UPDATE, DELETE, MATERIALIZE, etc.

    def get_all_commands(self) -> Set[str]:
        return self.commands

    def get_statement(self, commands: Set[str]) -> str:
        return f"ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{self.table} " + ", ".join(commands)


@dataclass
class LightweightDeleteMutationRunner(MutationRunner):
    predicate: str = field(kw_only=True)
    partition: str | None = field(default=None, kw_only=True)

    def get_all_commands(self) -> Set[str]:
        partition_suffix = f" IN PARTITION '{self.partition}'" if self.partition else ""
        return {f"UPDATE _row_exists = 0{partition_suffix} WHERE {self.predicate}"}

    def get_statement(self, commands: Set[str]) -> str:
        # XXX: lightweight deletes should only be called with the same command represented by the predicate
        if commands != self.get_all_commands():
            raise ValueError(f"unexpected commands: {commands!r}")

        partition_clause = f" IN PARTITION '{self.partition}'" if self.partition else ""
        return f"DELETE FROM {settings.CLICKHOUSE_DATABASE}.{self.table}{partition_clause} WHERE {self.predicate}"
