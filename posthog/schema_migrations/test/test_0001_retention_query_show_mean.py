import importlib


def test_retention_query_show_mean_migration():
    migration_module = importlib.import_module("posthog.schema_migrations.0001_retention_query_show_mean")
    migration = migration_module.Migration()

    # Test non-retention query is unchanged
    other_query = {"kind": "NotRetentionQuery"}
    assert migration.transform(other_query) == other_query

    # Test query with no retentionFilter is unchanged
    no_filter_query = {"kind": "RetentionQuery", "retentionFilter": None}
    assert migration.transform(no_filter_query) == no_filter_query

    # Test showMean=True converts to simple
    query_show_mean_true = {"kind": "RetentionQuery", "retentionFilter": {"showMean": True}}
    assert migration.transform(query_show_mean_true) == {
        "kind": "RetentionQuery",
        "retentionFilter": {"meanRetentionCalculation": "simple"},
    }

    # Test showMean=False converts to none
    query_show_mean_false = {"kind": "RetentionQuery", "retentionFilter": {"showMean": False}}
    assert migration.transform(query_show_mean_false) == {
        "kind": "RetentionQuery",
        "retentionFilter": {"meanRetentionCalculation": "none"},
    }

    # Test existing meanRetentionCalculation is preserved and showMean is removed
    query_with_both = {
        "kind": "RetentionQuery",
        "retentionFilter": {"showMean": True, "meanRetentionCalculation": "weighted"},
    }
    assert migration.transform(query_with_both) == {
        "kind": "RetentionQuery",
        "retentionFilter": {"meanRetentionCalculation": "weighted"},
    }
