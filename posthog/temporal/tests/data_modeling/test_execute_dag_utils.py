from collections import defaultdict

from posthog.temporal.data_modeling.workflows.execute_dag import _classify_level_nodes


def test_suspended_node_blocks_downstream_level() -> None:
    downstreams: dict[str, set[str]] = defaultdict(set)
    downstreams["a"] = {"b"}
    failed_node_set: set[str] = set()

    execute_nodes, skip_nodes, ephemeral_nodes, blocked_node_ids = _classify_level_nodes(
        ["a"],
        downstreams=downstreams,
        failed_node_set=failed_node_set,
        suspended_node_ids={"a"},
        ephemeral_node_set=set(),
        engine="clickhouse",
    )

    assert execute_nodes == []
    assert skip_nodes == [("a", "Node is suspended for clickhouse")]
    assert ephemeral_nodes == []
    assert blocked_node_ids == {"a"}

    failed_node_set.update(blocked_node_ids)

    execute_nodes, skip_nodes, ephemeral_nodes, blocked_node_ids = _classify_level_nodes(
        ["b"],
        downstreams=downstreams,
        failed_node_set=failed_node_set,
        suspended_node_ids={"a"},
        ephemeral_node_set=set(),
        engine="clickhouse",
    )

    assert execute_nodes == []
    assert skip_nodes == [("b", "Upstream node a failed")]
    assert ephemeral_nodes == []
    assert blocked_node_ids == set()
