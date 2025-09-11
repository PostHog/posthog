from typing import Any, Optional

import pytest
from unittest.mock import Mock

from posthog.schema import NodeKind

from posthog.schema_migrations import LATEST_VERSIONS, MIGRATIONS, SchemaMigration
from posthog.schema_migrations.upgrade_manager import upgrade_insight, upgrade_query


class SampleMigration(SchemaMigration):
    targets = {NodeKind.TRENDS_QUERY: 1}

    def transform(self, query):
        query["aggregationGroupTypeIndex"] = query.pop("aggregation_group_type_index")
        return query


@pytest.fixture(autouse=True)
def setup_migrations():
    LATEST_VERSIONS.clear()
    MIGRATIONS.clear()

    MIGRATIONS[NodeKind.TRENDS_QUERY] = {1: SampleMigration()}
    LATEST_VERSIONS[NodeKind.TRENDS_QUERY] = 2

    yield


def test_upgrade_insight_context_manager():
    mock_insight = Mock()
    mock_insight.query = {"kind": NodeKind.TRENDS_QUERY, "version": 1, "aggregation_group_type_index": 2}
    upgraded_query = {"kind": NodeKind.TRENDS_QUERY, "version": 2, "aggregationGroupTypeIndex": 2}

    with upgrade_insight(mock_insight):
        assert mock_insight.query == upgraded_query


def test_upgrade_query_manager():
    mock_insight = Mock()
    mock_insight.filters = {"aggregation_group_type_index": 2}
    mock_insight.query = None

    with upgrade_query(mock_insight):
        query: Optional[dict[str, Any]] = mock_insight.query
        assert query is not None
        assert query["aggregationGroupTypeIndex"] == 2
