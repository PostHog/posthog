from posthog.schema_migrations.base import SchemaMigration

# Data warehouse series nodes use a different kind per insight type; exclusions have no
# data warehouse member, so table_name-shaped exclusion items fall through to EventsNode.
SERIES_DATA_WAREHOUSE_KIND = {
    "TrendsQuery": "DataWarehouseNode",
    "StickinessQuery": "DataWarehouseNode",
    "LifecycleQuery": "DataWarehouseNode",
    "CalendarHeatmapQuery": "DataWarehouseNode",
    "FunnelsQuery": "FunnelsDataWarehouseNode",
}


class Migration(SchemaMigration):
    """Stamp the `kind` discriminator onto entity nodes (series, funnel exclusions) that lack it.

    These unions used to be undiscriminated: pydantic's smart union coerced a kind-less dict
    to the first structurally-matching member, so stored insights contain series items like
    `{"event": "$pageview"}` or `{}`. With the unions now discriminated on `kind`, such items
    fail validation with `union_tag_not_found` unless the tag is backfilled. The stamping
    mirrors the old coercion: event-shaped (and empty) dicts were EventsNode, id-only dicts
    were ActionsNode, table_name-shaped dicts were the data warehouse node.
    """

    targets = {
        "TrendsQuery": 3,
        "StickinessQuery": 3,
        "LifecycleQuery": 1,
        "CalendarHeatmapQuery": 1,
        "FunnelsQuery": 1,
    }

    def transform(self, query: dict) -> dict:
        data_warehouse_kind = SERIES_DATA_WAREHOUSE_KIND[str(query.get("kind"))]

        series = query.get("series")
        if isinstance(series, list):
            query["series"] = [self._stamp_kind(item, data_warehouse_kind) for item in series]

        funnels_filter = query.get("funnelsFilter")
        if query.get("kind") == "FunnelsQuery" and isinstance(funnels_filter, dict):
            exclusions = funnels_filter.get("exclusions")
            if isinstance(exclusions, list):
                query["funnelsFilter"] = {
                    **funnels_filter,
                    "exclusions": [self._stamp_kind(item, None) for item in exclusions],
                }

        return query

    @staticmethod
    def _stamp_kind(item: object, data_warehouse_kind: str | None) -> object:
        if not isinstance(item, dict) or "kind" in item:
            return item
        if data_warehouse_kind is not None and "table_name" in item:
            kind = data_warehouse_kind
        elif "id" in item and "event" not in item:
            kind = "ActionsNode"
        else:
            kind = "EventsNode"
        return {**item, "kind": kind}
