from posthog.schema import NodeKind
from posthog.schema_migrations.base import SchemaMigration


class TestMigration(SchemaMigration):
    targets = {NodeKind.EVENTS_QUERY: 1}

    def transform(self, doc: dict) -> dict:
        doc["some_key"] = "some_value"
        return doc


def test_should_run_returns_true_for_matching_version():
    migration = TestMigration()
    doc = {"kind": NodeKind.EVENTS_QUERY, "v": 1}
    assert migration.should_run(doc) is True


def test_should_run_returns_false_for_non_matching_version():
    migration = TestMigration()
    doc = {"kind": NodeKind.EVENTS_QUERY, "v": 2}
    assert migration.should_run(doc) is False


def test_should_run_returns_false_for_non_matching_kind():
    migration = TestMigration()
    doc = {"kind": NodeKind.HOG_QL_QUERY, "v": 1}
    assert migration.should_run(doc) is False


def test_should_run_handles_missing_version():
    migration = TestMigration()
    doc = {"kind": NodeKind.EVENTS_QUERY}
    assert migration.should_run(doc) is True


def test_transform_updates_doc():
    migration = TestMigration()
    doc = {"kind": NodeKind.EVENTS_QUERY, "v": 1}
    result = migration(doc)
    assert result["some_key"] == "some_value"


def test_transform_updates_version():
    migration = TestMigration()
    doc = {"kind": NodeKind.EVENTS_QUERY, "v": 1}
    result = migration(doc)
    assert result["v"] == 2
