from posthog.schema import NodeKind

from posthog.schema_migrations.base import SchemaMigration


class TestMigration(SchemaMigration):
    targets = {NodeKind.EVENTS_QUERY: 1}

    def transform(self, query: dict) -> dict:
        query["some_key"] = "some_value"
        return query


def test_should_run_returns_true_for_matching_version():
    migration = TestMigration()
    query = {"kind": NodeKind.EVENTS_QUERY, "version": 1}
    assert migration.should_run(query) is True


def test_should_run_returns_false_for_non_matching_version():
    migration = TestMigration()
    query = {"kind": NodeKind.EVENTS_QUERY, "version": 2}
    assert migration.should_run(query) is False


def test_should_run_returns_false_for_non_matching_kind():
    migration = TestMigration()
    query = {"kind": NodeKind.HOG_QL_QUERY, "version": 1}
    assert migration.should_run(query) is False


def test_should_run_handles_missing_version():
    migration = TestMigration()
    query = {"kind": NodeKind.EVENTS_QUERY}
    assert migration.should_run(query) is True


def test_transform_updates_query():
    migration = TestMigration()
    query = {"kind": NodeKind.EVENTS_QUERY, "version": 1}
    result = migration(query)
    assert result["some_key"] == "some_value"


def test_transform_updates_version():
    migration = TestMigration()
    query = {"kind": NodeKind.EVENTS_QUERY, "version": 1}
    result = migration(query)
    assert result["version"] == 2


def test_should_accept_none_version():
    migration = TestMigration()
    query = {"kind": NodeKind.EVENTS_QUERY, "version": None}
    result = migration(query)
    assert result["version"] == 2
