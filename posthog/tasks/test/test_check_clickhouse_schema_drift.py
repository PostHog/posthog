from posthog.tasks.check_clickhouse_schema_drift import get_clickhouse_schema_drift


def test_get_clickhouse_schema_drift() -> None:
    # No drift
    clickhouse_nodes = [("node1",), ("node2",), ("node3",)]
    clickhouse_schema = [
        ("table1", "schema1", "host1"),
        ("table1", "schema1", "host2"),
        ("table1", "schema1", "host3"),
        ("table2", "schema2", "host1"),
        ("table2", "schema2", "host2"),
        ("table2", "schema2", "host3"),
    ]
    diff = get_clickhouse_schema_drift(clickhouse_nodes, clickhouse_schema)
    assert diff == []

    # Different schema on 1 table, 1 node
    clickhouse_nodes = [("node1",), ("node2",), ("node3",)]
    clickhouse_schema = [
        ("table1", "schema1", "host1"),
        ("table1", "schema1", "host2"),
        ("table1", "schema1", "host3"),
        ("table2", "schema2", "host1"),
        ("table2", "schema2", "host2"),
        ("table2", "schema2-different-bis", "host3"),
    ]
    diff = get_clickhouse_schema_drift(clickhouse_nodes, clickhouse_schema)
    assert diff == ["table2"]

    # Different schema on 1 table, 2 nodes
    clickhouse_nodes = [("node1",), ("node2",), ("node3",)]
    clickhouse_schema = [
        ("table1", "schema1", "host1"),
        ("table1", "schema1", "host2"),
        ("table1", "schema1", "host3"),
        ("table2", "schema2", "host1"),
        ("table2", "schema2-different", "host2"),
        ("table2", "schema2-different-bis", "host3"),
    ]
    diff = get_clickhouse_schema_drift(clickhouse_nodes, clickhouse_schema)
    assert diff == ["table2"]

    # Different schema on 2 tables, 1 node
    clickhouse_nodes = [("node1",), ("node2",), ("node3",)]
    clickhouse_schema = [
        ("table1", "schema1", "host1"),
        ("table1", "schema1", "host2"),
        ("table1", "schema1-different", "host3"),
        ("table2", "schema2", "host1"),
        ("table2", "schema2", "host2"),
        ("table2", "schema2-different", "host3"),
    ]
    diff = get_clickhouse_schema_drift(clickhouse_nodes, clickhouse_schema)
    assert diff == ["table1", "table2"]

    # Different schema on 2 tables, 2 node
    clickhouse_nodes = [("node1",), ("node2",), ("node3",)]
    clickhouse_schema = [
        ("table1", "schema1", "host1"),
        ("table1", "schema1-different", "host2"),
        ("table1", "schema1", "host3"),
        ("table2", "schema2", "host1"),
        ("table2", "schema2", "host2"),
        ("table2", "schema2-different", "host3"),
    ]
    diff = get_clickhouse_schema_drift(clickhouse_nodes, clickhouse_schema)
    assert diff == ["table1", "table2"]

    # 1 table missing on 1 node
    clickhouse_nodes = [("node1",), ("node2",), ("node3",)]
    clickhouse_schema = [
        ("table1", "schema1", "host1"),
        ("table1", "schema1", "host2"),
        ("table1", "schema1", "host3"),
        ("table2", "schema2", "host1"),
        ("table2", "schema2", "host2"),
    ]
    diff = get_clickhouse_schema_drift(clickhouse_nodes, clickhouse_schema)
    assert diff == ["table2"]

    # 1 table missing on 2 nodes
    clickhouse_nodes = [("node1",), ("node2",), ("node3",)]
    clickhouse_schema = [
        ("table1", "schema1", "host1"),
        ("table1", "schema1", "host2"),
        ("table1", "schema1", "host3"),
        ("table2", "schema2", "host1"),
    ]
    diff = get_clickhouse_schema_drift(clickhouse_nodes, clickhouse_schema)
    assert diff == ["table2"]

    # 2 tables missing on 1 node
    clickhouse_nodes = [("node1",), ("node2",), ("node3",)]
    clickhouse_schema = [
        ("table1", "schema1", "host1"),
        ("table1", "schema1", "host2"),
        ("table2", "schema2", "host1"),
        ("table2", "schema2", "host2"),
    ]
    diff = get_clickhouse_schema_drift(clickhouse_nodes, clickhouse_schema)
    assert diff == ["table1", "table2"]

    # 2 tables missing on 2 nodes
    clickhouse_nodes = [("node1",), ("node2",), ("node3",)]
    clickhouse_schema = [
        ("table1", "schema1", "host1"),
        ("table2", "schema2", "host1"),
    ]
    diff = get_clickhouse_schema_drift(clickhouse_nodes, clickhouse_schema)
    assert diff == ["table1", "table2"]
