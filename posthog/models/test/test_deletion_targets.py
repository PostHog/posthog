from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
from unittest.mock import Mock, patch

from django.test import override_settings

from posthog.clickhouse.cluster import ClickhouseCluster, HostInfo
from posthog.models.deletion_targets import DeletionTarget, UnreachableTargetError, dispatchable_here, placement_for

# One data node each, so a table present on one cluster and absent from the other is the only
# difference between them. That is the topology the placement resolution exists for and the one no
# single-node test environment can reproduce.
_HOSTS_BY_CLUSTER: dict[str, list[tuple]] = {
    "posthog": [("data1", 9000, 1, 1, "online", "data")],
    "events": [("events1", 9000, 1, 1, "online", "data")],
}

_OFF_CLUSTER_TARGET = DeletionTarget(
    data_table="sharded_events_json",
    read_table="events_json",
    optional=True,
    cluster_setting="CLICKHOUSE_EVENTS_CLUSTER",
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
    with _cluster_with({"data1": set(), "events1": {"sharded_events_json"}}) as cluster:
        placement = placement_for(cluster, _OFF_CLUSTER_TARGET)

        assert placement is not None
        assert placement.cluster.data_cluster_name == "events"
        assert placement.cluster is not cluster


@override_settings(CLICKHOUSE_EVENTS_CLUSTER="events")
def test_placement_prefers_the_handle_in_hand_over_a_sibling() -> None:
    # Two cluster names covering the same nodes is what the dev stack and CI do. Building a sibling
    # there would sweep the same rows twice, so the handle in hand has to win.
    with _cluster_with({"data1": {"sharded_events_json"}, "events1": {"sharded_events_json"}}) as cluster:
        placement = placement_for(cluster, _OFF_CLUSTER_TARGET)

        assert placement is not None
        assert placement.cluster is cluster


@override_settings(CLICKHOUSE_EVENTS_CLUSTER="events")
def test_dispatchable_here_refuses_a_target_another_cluster_carries() -> None:
    # Sweeps that fan out over a single handle (property removal, the queued-uuid drain) have no way
    # to reach another cluster's shards. Answering False would put back the silent skip that
    # completes a request while the rows survive.
    with _cluster_with({"data1": set(), "events1": {"sharded_events_json"}}) as cluster:
        with pytest.raises(UnreachableTargetError):
            dispatchable_here(cluster, _OFF_CLUSTER_TARGET)
