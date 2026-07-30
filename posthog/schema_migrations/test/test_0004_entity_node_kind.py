import importlib

from parameterized import parameterized

from posthog.schema import FunnelsQuery, LifecycleQuery, TrendsQuery

from posthog.schema_migrations.upgrade import upgrade


def _get_migration():
    migration_module = importlib.import_module("posthog.schema_migrations.0004_entity_node_kind")
    return migration_module.Migration()


@parameterized.expand(
    [
        # (case_name, query_kind, series_item, expected_kind)
        ("event_shaped", "TrendsQuery", {"event": "$pageview"}, "EventsNode"),
        ("empty_dict", "TrendsQuery", {}, "EventsNode"),
        ("math_only", "TrendsQuery", {"math": "dau", "event": "$pageview"}, "EventsNode"),
        ("id_only", "TrendsQuery", {"id": 5}, "ActionsNode"),
        ("id_and_event", "TrendsQuery", {"id": "$pageview", "event": "$pageview"}, "EventsNode"),
        ("data_warehouse_shaped", "TrendsQuery", {"table_name": "orders", "id": "orders"}, "DataWarehouseNode"),
        ("group_shaped", "TrendsQuery", {"nodes": [{"kind": "EventsNode"}], "operator": "OR"}, "GroupNode"),
        ("funnels_event_shaped", "FunnelsQuery", {"event": "$pageview"}, "EventsNode"),
        (
            "funnels_data_warehouse_shaped",
            "FunnelsQuery",
            {"table_name": "orders", "id": "orders"},
            "FunnelsDataWarehouseNode",
        ),
        ("funnels_group_shaped", "FunnelsQuery", {"nodes": [{"kind": "EventsNode"}], "operator": "OR"}, "GroupNode"),
        ("lifecycle_event_shaped", "LifecycleQuery", {"event": "$pageview"}, "EventsNode"),
        (
            "lifecycle_data_warehouse_shaped",
            "LifecycleQuery",
            {"table_name": "orders", "id": "orders"},
            "LifecycleDataWarehouseNode",
        ),
        ("stickiness_event_shaped", "StickinessQuery", {"event": "$pageview"}, "EventsNode"),
        (
            "stickiness_data_warehouse_shaped",
            "StickinessQuery",
            {"table_name": "orders", "id": "orders"},
            "DataWarehouseNode",
        ),
        # StickinessQuery.series has no GroupNode member — group-shaped items were invalid
        # before discrimination and stay invalid (stamped EventsNode) rather than resurrected.
        (
            "stickiness_group_shaped",
            "StickinessQuery",
            {"nodes": [{"kind": "EventsNode"}], "operator": "OR"},
            "EventsNode",
        ),
        ("calendar_heatmap_event_shaped", "CalendarHeatmapQuery", {"event": "$pageview"}, "EventsNode"),
        (
            "calendar_heatmap_data_warehouse_shaped",
            "CalendarHeatmapQuery",
            {"table_name": "orders", "id": "orders"},
            "DataWarehouseNode",
        ),
    ]
)
def test_kindless_series_item_gets_stamped(_name, query_kind, series_item, expected_kind):
    migration = _get_migration()
    result = migration.transform({"kind": query_kind, "series": [series_item]})
    assert result["series"][0] == {**series_item, "kind": expected_kind}


@parameterized.expand(
    [
        # (case_name, series) — items the migration must pass through untouched
        ("tagged_item", [{"kind": "ActionsNode", "id": 5}]),
        ("string_placeholder", ["{SIGNED_UP}"]),
        ("null_item", [None]),
    ]
)
def test_non_stampable_series_items_unchanged(_name, series):
    migration = _get_migration()
    result = migration.transform({"kind": "TrendsQuery", "series": list(series)})
    assert result["series"] == series


def test_missing_or_invalid_series_unchanged():
    migration = _get_migration()
    assert migration.transform({"kind": "TrendsQuery"}) == {"kind": "TrendsQuery"}
    assert migration.transform({"kind": "TrendsQuery", "series": None}) == {"kind": "TrendsQuery", "series": None}


def test_funnel_exclusions_get_stamped():
    migration = _get_migration()
    query = {
        "kind": "FunnelsQuery",
        "series": [{"kind": "EventsNode", "event": "a"}, {"kind": "EventsNode", "event": "b"}],
        "funnelsFilter": {
            "exclusions": [
                {"event": "$pageleave", "funnelFromStep": 0, "funnelToStep": 1},
                {"id": 5, "funnelFromStep": 0, "funnelToStep": 1},
                # exclusions have no GroupNode member, so group-shaped items fall through
                {"nodes": [{"kind": "EventsNode"}], "operator": "OR"},
            ],
            "funnelVizType": "steps",
        },
    }
    result = migration.transform(query)
    assert [e["kind"] for e in result["funnelsFilter"]["exclusions"]] == ["EventsNode", "ActionsNode", "EventsNode"]
    assert result["funnelsFilter"]["funnelVizType"] == "steps"


def test_upgraded_stored_funnels_query_validates():
    # The end-to-end guarantee: a stored insight query written under the undiscriminated
    # unions passes pydantic validation again after upgrade().
    stored = {
        "kind": "FunnelsQuery",
        "series": [{"event": "signed_up"}, {"event": "activated"}],
        "funnelsFilter": {"exclusions": [{"event": "$pageleave", "funnelFromStep": 0, "funnelToStep": 1}]},
    }
    upgraded = upgrade(stored)
    query = FunnelsQuery.model_validate(upgraded)
    assert [s.kind for s in query.series] == ["EventsNode", "EventsNode"]
    assert query.funnelsFilter is not None and query.funnelsFilter.exclusions is not None
    assert query.funnelsFilter.exclusions[0].kind == "EventsNode"
    assert query.version == 2


def test_upgraded_stored_trends_query_validates():
    stored = {
        "kind": "InsightVizNode",
        "source": {
            "kind": "TrendsQuery",
            "series": [
                {"math": "dau", "event": "$pageview"},
                {"nodes": [{"kind": "EventsNode", "event": "$pageview"}], "operator": "OR"},
            ],
        },
    }
    upgraded = upgrade(stored)
    query = TrendsQuery.model_validate(upgraded["source"])
    assert [s.kind for s in query.series] == ["EventsNode", "GroupNode"]


def test_upgraded_stored_lifecycle_warehouse_query_validates():
    stored = {
        "kind": "LifecycleQuery",
        "series": [
            {
                "table_name": "orders",
                "id": "orders",
                "timestamp_field": "created_at",
                "created_at_field": "created_at",
                "aggregation_target_field": "customer_id",
            }
        ],
    }
    upgraded = upgrade(stored)
    query = LifecycleQuery.model_validate(upgraded)
    assert query.series[0].kind == "LifecycleDataWarehouseNode"
