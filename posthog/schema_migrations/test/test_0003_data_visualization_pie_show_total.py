import importlib

import pytest

from posthog.schema import QuerySchemaRoot

import posthog.schema_migrations as schema_migrations_module
from posthog.schema_migrations import LATEST_VERSIONS, MIGRATIONS, _discover_migrations
from posthog.schema_migrations.upgrade import upgrade


@pytest.fixture
def real_migrations():
    # upgrade() reads the process-global registry; force the real migrations to be
    # (re)discovered here and restore prior state so sibling test files that mock the
    # registry are unaffected by ordering.
    saved_versions = dict(LATEST_VERSIONS)
    saved_migrations = {kind: dict(versions) for kind, versions in MIGRATIONS.items()}
    saved_flag = schema_migrations_module._migrations_discovered

    LATEST_VERSIONS.clear()
    MIGRATIONS.clear()
    schema_migrations_module._migrations_discovered = False
    _discover_migrations()
    try:
        yield
    finally:
        LATEST_VERSIONS.clear()
        LATEST_VERSIONS.update(saved_versions)
        MIGRATIONS.clear()
        MIGRATIONS.update(saved_migrations)
        schema_migrations_module._migrations_discovered = saved_flag


def test_legacy_pie_chart_query_upgrades_and_validates(real_migrations):
    # A real saved pie chart that still carries the removed `showPieTotal` key. Before this
    # migration existed, `upgrade()` left it untouched and `QuerySchemaRoot.model_validate`
    # raised (ChartSettings is `extra="forbid"`) — the crash users hit. Delete or rename
    # 0003 and this test fails at the validate() call below.
    legacy = {
        "kind": "DataVisualizationNode",
        "source": {"kind": "HogQLQuery", "query": "select 1"},
        "chartSettings": {"showPieTotal": False},
    }

    upgraded = upgrade(legacy)

    QuerySchemaRoot.model_validate(upgraded)
    assert upgraded["chartSettings"] == {"pie": {"showTotal": False}}


@pytest.mark.parametrize(
    "query,expected",
    [
        (
            {"kind": "NotDataVisualizationNode", "chartSettings": {"showPieTotal": True}},
            {"kind": "NotDataVisualizationNode", "chartSettings": {"showPieTotal": True}},
        ),
        ({"kind": "DataVisualizationNode"}, {"kind": "DataVisualizationNode"}),
        (
            {"kind": "DataVisualizationNode", "chartSettings": {"showLegend": True}},
            {"kind": "DataVisualizationNode", "chartSettings": {"showLegend": True}},
        ),
        (
            {"kind": "DataVisualizationNode", "chartSettings": {"showPieTotal": False}},
            {"kind": "DataVisualizationNode", "chartSettings": {"pie": {"showTotal": False}}},
        ),
        (
            {
                "kind": "DataVisualizationNode",
                "chartSettings": {"showPieTotal": True, "pie": {"sliceContent": "values"}},
            },
            {"kind": "DataVisualizationNode", "chartSettings": {"pie": {"sliceContent": "values", "showTotal": True}}},
        ),
        (
            {"kind": "DataVisualizationNode", "chartSettings": {"showPieTotal": True, "pie": {"showTotal": False}}},
            {"kind": "DataVisualizationNode", "chartSettings": {"pie": {"showTotal": False}}},
        ),
    ],
    ids=[
        "non_data_visualization_node_untouched",
        "missing_chart_settings_untouched",
        "chart_settings_without_show_pie_total_untouched",
        "explicit_false_moves_into_pie_show_total",
        "merges_alongside_existing_pie_settings",
        "already_migrated_pie_show_total_wins",
    ],
)
def test_data_visualization_pie_show_total_migration(query, expected):
    migration_module = importlib.import_module("posthog.schema_migrations.0003_data_visualization_pie_show_total")
    assert migration_module.Migration().transform(query) == expected
