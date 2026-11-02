from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
from unittest.mock import Mock, patch

from django.test import override_settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster, HostInfo
from posthog.models.deletion_targets import (
    DeletionTarget,
    UnreachableTargetError,
    dispatchable_here,
    placement_for,
    sweep_clusters,
)

# Mirrors production. The main cluster shards across `data` nodes; the events cluster shards across
# nodes whose hostClusterRole is `events` and whose type is `offline`. Calling those nodes `data`
# here is what let the placement resolution pass its tests while finding nothing in production: a
# handle built for them assigns no shard numbers, so it has no shards to dispatch over and no host
# matching a `data` probe.
_HOSTS_BY_CLUSTER: dict[str, list[tuple]] = {
    "posthog": [("data1", 9000, 1, 1, "online", "data")],
    "events": [
        ("events1", 9000, 1, 1, "offline", "events"),
        ("events2", 9000, 2, 1, "offline", "events"),
    ],
}

_OFF_CLUSTER_TARGET = DeletionTarget(
    data_table="sharded_events_json",
    read_table="events_json",
    optional=True,
    cluster_setting="CLICKHOUSE_EVENTS_CLUSTER",
    node_role=NodeRole.EVENTS,
)


class _FakeClient:
    def __init__(self, tables: set[str]) -> None:
        self._tables = tables

    def execute(self, query: str, params: dict | None = None, *args: object, **kwargs: object) -> list[list[int]]:
        if "system.tables" in query:
            assert params is not None
            return [[1 if params["name"] in self._tables else 0]]
        raise AssertionError(f"unexpected query: {query}")


@contextmanager
def _cluster_with(tables_by_host: dict[str, set[str]]) -> Iterator[ClickhouseCluster]:
    """A handle on ``posthog`` whose hosts, and its siblings' hosts, carry the tables given."""
    bootstrap = Mock()
    bootstrap.execute = Mock(side_effect=lambda query, params: _HOSTS_BY_CLUSTER[params["name"]])

    def get_task_function(_self: ClickhouseCluster, host: HostInfo, fn: Callable) -> Callable:
        return lambda: fn(_FakeClient(tables_by_host[host.connection_info.host]))

    with patch.object(ClickhouseCluster, "_ClickhouseCluster__get_task_function", get_task_function):
        yield ClickhouseCluster(bootstrap, cluster="posthog")


@override_settings(CLICKHOUSE_EVENTS_CLUSTER="events")
def test_placement_routes_a_target_to_the_cluster_that_carries_it() -> None:
    with _cluster_with(
        {"data1": set(), "events1": {"sharded_events_json"}, "events2": {"sharded_events_json"}}
    ) as cluster:
        placement = placement_for(cluster, _OFF_CLUSTER_TARGET)

        assert placement is not None
        assert placement.cluster.data_cluster_name == "events"
        assert placement.cluster is not cluster


@override_settings(CLICKHOUSE_EVENTS_CLUSTER="events")
def test_placement_prefers_the_handle_in_hand_over_a_sibling() -> None:
    # Two cluster names covering the same nodes is what the dev stack and CI do. Building a sibling
    # there would sweep the same rows twice, so the handle in hand has to win.
    with _cluster_with(
        {"data1": {"sharded_events_json"}, "events1": {"sharded_events_json"}, "events2": {"sharded_events_json"}}
    ) as cluster:
        placement = placement_for(cluster, _OFF_CLUSTER_TARGET)

        assert placement is not None
        assert placement.cluster is cluster


@override_settings(CLICKHOUSE_EVENTS_CLUSTER="events")
def test_dispatchable_here_refuses_a_target_another_cluster_carries() -> None:
    # Sweeps that fan out over a single handle (property removal, the queued-uuid drain) have no way
    # to reach another cluster's shards. Answering False would put back the silent skip that
    # completes a request while the rows survive.
    with _cluster_with(
        {"data1": set(), "events1": {"sharded_events_json"}, "events2": {"sharded_events_json"}}
    ) as cluster:
        with pytest.raises(UnreachableTargetError):
            dispatchable_here(cluster, _OFF_CLUSTER_TARGET)


@override_settings(CLICKHOUSE_EVENTS_CLUSTER="events")
def test_sweep_clusters_lists_every_cluster_a_mutation_runs_on() -> None:
    # The delete predicate joins a dictionary, so the dictionary has to exist on each cluster this
    # returns. Missing one there means the mutation runs against nothing and reports success.
    with _cluster_with(
        {"data1": set(), "events1": {"sharded_events_json"}, "events2": {"sharded_events_json"}}
    ) as cluster:
        clusters = sweep_clusters(cluster, [_OFF_CLUSTER_TARGET])

        assert [handle.data_cluster_name for handle in clusters] == ["posthog", "events"]
        assert clusters[0] is cluster


@override_settings(CLICKHOUSE_EVENTS_CLUSTER="events")
def test_sweep_clusters_does_not_repeat_the_handle_in_hand() -> None:
    # Building the dictionary twice on one cluster is wasted work, and every sweep keyed off this
    # list would run its mutations twice.
    with _cluster_with(
        {"data1": {"sharded_events_json"}, "events1": {"sharded_events_json"}, "events2": {"sharded_events_json"}}
    ) as cluster:
        assert sweep_clusters(cluster, [_OFF_CLUSTER_TARGET]) == [cluster]


@override_settings(CLICKHOUSE_EVENTS_CLUSTER="events")
def test_a_sibling_shards_over_the_role_its_target_declares() -> None:
    # The mutation dispatches over placement.cluster.shards. A handle that only reads shard numbers
    # off `data` nodes leaves that empty for the events cluster, so the sweep reaches nothing and
    # the target looks absent rather than unreachable, which is how it went silent in production.
    tables = {"data1": set(), "events1": {"sharded_events_json"}, "events2": {"sharded_events_json"}}
    with _cluster_with(tables) as cluster:
        placement = placement_for(cluster, _OFF_CLUSTER_TARGET)

        assert placement is not None
        assert sorted(placement.cluster.shards) == [1, 2]
        assert placement.cluster.shard_role == NodeRole.EVENTS
