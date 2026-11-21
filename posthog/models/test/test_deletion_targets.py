from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
from unittest.mock import Mock, patch

from django.test import override_settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster, HostInfo
from posthog.models.deletion_targets import (
    EVENTS_JSON,
    FLAG_EVALUATIONS,
    FLAG_EVALUATIONS_JSON,
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
    "flags": [
        ("flags1", 9000, 1, 1, "offline", "flags"),
        ("flags2", 9000, 1, 2, "offline", "flags"),
    ],
}


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


# The registry's own entries, so a target that names the wrong cluster setting or node role fails here
# rather than in a production deletion run.
_REGISTERED_OFF_CLUSTER_TARGETS = [
    pytest.param(EVENTS_JSON, "events", [1, 2], NodeRole.EVENTS, id="events_json"),
    pytest.param(FLAG_EVALUATIONS, "flags", [1], NodeRole.FLAGS, id="flag_evaluations"),
    pytest.param(FLAG_EVALUATIONS_JSON, "flags", [1], NodeRole.FLAGS, id="flag_evaluations_json"),
]


@override_settings(CLICKHOUSE_EVENTS_CLUSTER="events", CLICKHOUSE_FLAGS_CLUSTER="flags")
@pytest.mark.parametrize("target,cluster_name,shards,shard_role", _REGISTERED_OFF_CLUSTER_TARGETS)
def test_placement_routes_a_registered_target_to_the_cluster_that_carries_it(
    target: DeletionTarget, cluster_name: str, shards: list[int], shard_role: NodeRole
) -> None:
    # The mutation dispatches over placement.cluster.shards. A handle that only reads shard numbers
    # off `data` nodes leaves that empty for a cluster that shards across another role, so the sweep
    # reaches nothing and the target looks absent rather than unreachable.
    tables = {"data1": set(), **{host[0]: {target.data_table} for host in _HOSTS_BY_CLUSTER[cluster_name]}}
    with _cluster_with(tables) as cluster:
        placement = placement_for(cluster, target)

        assert placement is not None
        assert placement.cluster is not cluster
        assert placement.cluster.data_cluster_name == cluster_name
        assert placement.cluster.shard_role == shard_role
        assert sorted(placement.cluster.shards) == shards


@override_settings(CLICKHOUSE_EVENTS_CLUSTER="events")
def test_placement_prefers_the_handle_in_hand_over_a_sibling() -> None:
    # Two cluster names covering the same nodes is what the dev stack and CI do. Building a sibling
    # there would sweep the same rows twice, so the handle in hand has to win.
    with _cluster_with(
        {"data1": {"sharded_events_json"}, "events1": {"sharded_events_json"}, "events2": {"sharded_events_json"}}
    ) as cluster:
        placement = placement_for(cluster, EVENTS_JSON)

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
            dispatchable_here(cluster, EVENTS_JSON)


@override_settings(CLICKHOUSE_EVENTS_CLUSTER="events")
def test_sweep_clusters_lists_every_cluster_a_mutation_runs_on() -> None:
    # The delete predicate joins a dictionary, so the dictionary has to exist on each cluster this
    # returns. Missing one there means the mutation runs against nothing and reports success.
    with _cluster_with(
        {"data1": set(), "events1": {"sharded_events_json"}, "events2": {"sharded_events_json"}}
    ) as cluster:
        clusters = sweep_clusters(cluster, [EVENTS_JSON])

        assert [handle.data_cluster_name for handle in clusters] == ["posthog", "events"]
        assert clusters[0] is cluster


@override_settings(CLICKHOUSE_EVENTS_CLUSTER="events")
def test_sweep_clusters_does_not_repeat_the_handle_in_hand() -> None:
    # Building the dictionary twice on one cluster is wasted work, and every sweep keyed off this
    # list would run its mutations twice.
    with _cluster_with(
        {"data1": {"sharded_events_json"}, "events1": {"sharded_events_json"}, "events2": {"sharded_events_json"}}
    ) as cluster:
        assert sweep_clusters(cluster, [EVENTS_JSON]) == [cluster]
