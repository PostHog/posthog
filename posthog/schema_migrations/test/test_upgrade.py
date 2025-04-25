from posthog.schema import NodeKind
from posthog.schema_migrations import LATEST_VERSIONS, SchemaMigration, MIGRATIONS
from posthog.schema_migrations.upgrade import upgrade
import pytest


class SampleUpgrade(SchemaMigration):
    targets = {NodeKind.TRENDS_QUERY: 1}

    def transform(self, query):
        query["mode"] = "on" if query.pop("flag") else "off"
        return query


@pytest.fixture(autouse=True)
def setup_migrations():
    LATEST_VERSIONS.clear()
    MIGRATIONS.clear()

    MIGRATIONS[NodeKind.TRENDS_QUERY] = {1: SampleUpgrade()}
    LATEST_VERSIONS[NodeKind.TRENDS_QUERY] = 2

    yield


def test_simple_upgrade():
    query = {"kind": NodeKind.TRENDS_QUERY, "v": 1, "flag": True}
    got = upgrade(query)
    assert got == {"kind": NodeKind.TRENDS_QUERY, "v": 2, "mode": "on"}


def test_already_latest():
    query = {"kind": NodeKind.TRENDS_QUERY, "v": LATEST_VERSIONS[NodeKind.TRENDS_QUERY]}
    assert upgrade(query) == query
