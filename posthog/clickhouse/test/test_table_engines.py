from posthog.clickhouse.table_engines import MergeTreeEngine, ReplicationScheme


class TestMergeTreeEngine:
    def test_basic_merge_tree_engine(self):
        engine = MergeTreeEngine("test_table", replication_scheme=ReplicationScheme.NOT_SHARDED)
        result = str(engine)
        assert result == "MergeTree()"

    def test_replicated_merge_tree_engine(self):
        engine = MergeTreeEngine("test_table", replication_scheme=ReplicationScheme.REPLICATED)
        result = str(engine)
        # Should contain the ReplicatedMergeTree pattern with zk path and replica
        assert "ReplicatedMergeTree(" in result
        assert "/clickhouse/tables/" in result
        assert "posthog.test_table" in result

    def test_merge_tree_engine_with_storage_policy(self):
        engine = MergeTreeEngine(
            "test_table", replication_scheme=ReplicationScheme.NOT_SHARDED, storage_policy="s3_policy"
        )
        result = str(engine)
        # Storage policy is no longer added to engine string - handled by table templates
        assert result == "MergeTree()"

    def test_replicated_merge_tree_engine_with_storage_policy(self):
        engine = MergeTreeEngine(
            "test_table", replication_scheme=ReplicationScheme.REPLICATED, storage_policy="s3_policy"
        )
        result = str(engine)
        # Should contain ReplicatedMergeTree but storage policy is handled by table templates
        assert "ReplicatedMergeTree(" in result
        assert "SETTINGS storage_policy" not in result

    def test_merge_tree_engine_without_storage_policy(self):
        engine = MergeTreeEngine("test_table", replication_scheme=ReplicationScheme.NOT_SHARDED)
        result = str(engine)
        # Should not contain SETTINGS when no storage_policy is provided
        assert "SETTINGS" not in result

    def test_storage_policy_none_doesnt_add_settings(self):
        engine = MergeTreeEngine("test_table", replication_scheme=ReplicationScheme.NOT_SHARDED, storage_policy=None)
        result = str(engine)
        assert "SETTINGS" not in result
