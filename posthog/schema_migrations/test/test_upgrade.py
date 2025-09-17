import pytest

from posthog.schema import NodeKind

from posthog.schema_migrations import LATEST_VERSIONS, MIGRATIONS, SchemaMigration
from posthog.schema_migrations.upgrade import upgrade


class SampleMigration(SchemaMigration):
    targets = {NodeKind.TRENDS_QUERY: 1}

    def transform(self, query):
        query["mode"] = "on" if query.pop("flag") else "off"
        return query


class EventsNodeMigration(SchemaMigration):
    targets = {NodeKind.EVENTS_NODE: 1}

    def transform(self, query):
        if "event" in query:
            query["name"] = query.pop("event")
        return query


@pytest.fixture(autouse=True)
def setup_migrations():
    LATEST_VERSIONS.clear()
    MIGRATIONS.clear()

    MIGRATIONS[NodeKind.TRENDS_QUERY] = {1: SampleMigration()}
    MIGRATIONS[NodeKind.EVENTS_NODE] = {1: EventsNodeMigration()}
    LATEST_VERSIONS[NodeKind.TRENDS_QUERY] = 2
    LATEST_VERSIONS[NodeKind.EVENTS_NODE] = 2

    yield


def test_simple_migration():
    query = {"kind": NodeKind.TRENDS_QUERY, "version": 1, "flag": True}
    got = upgrade(query)
    assert got == {"kind": NodeKind.TRENDS_QUERY, "version": 2, "mode": "on"}


def test_nested_source_migration():
    query = {"kind": NodeKind.INSIGHT_VIZ_NODE, "source": {"kind": NodeKind.TRENDS_QUERY, "flag": True}}
    got = upgrade(query)
    assert got == {
        "kind": NodeKind.INSIGHT_VIZ_NODE,
        "source": {"kind": NodeKind.TRENDS_QUERY, "version": 2, "mode": "on"},
    }


def test_nested_array_migration():
    query = {
        "kind": NodeKind.TRENDS_QUERY,
        "version": 2,
        "series": [
            {"kind": NodeKind.EVENTS_NODE, "version": 1, "event": "pageview"},
            {"kind": NodeKind.EVENTS_NODE, "version": 1, "event": "signup"},
        ],
    }
    got = upgrade(query)
    assert got == {
        "kind": NodeKind.TRENDS_QUERY,
        "version": 2,
        "series": [
            {"kind": NodeKind.EVENTS_NODE, "version": 2, "name": "pageview"},
            {"kind": NodeKind.EVENTS_NODE, "version": 2, "name": "signup"},
        ],
    }


def test_already_latest():
    query = {"kind": NodeKind.TRENDS_QUERY, "version": LATEST_VERSIONS[NodeKind.TRENDS_QUERY]}
    assert upgrade(query) == query
