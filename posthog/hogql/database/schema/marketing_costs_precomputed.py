from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DateTimeDatabaseField, FieldOrTable, LazyTable, LazyTableToAdd
from posthog.hogql.database.schema.marketing_costs_preaggregated import MarketingCostsPreaggregatedTable

# Deduplicated read interface over `marketing_costs_preaggregated`. `job_id` is in the raw ReplacingMergeTree
# sort key, so a re-materialized cell survives as several rows and a bare SUM double-counts; this view collapses
# each cell to its latest job via argMax. Read this, not the raw table. Named `_precomputed` because it holds
# only materialized rows (S3-fallback sources are absent) — the precomputed subset, not the complete cost set.

MARKETING_COSTS_PRECOMPUTED_VIEW_NAME = "marketing_costs_precomputed"
_RAW = "marketing_costs_preaggregated"

_RAW_FIELDS = MarketingCostsPreaggregatedTable().fields  # reuse the raw column defs so the view can't drift
_INTERNAL = {"job_id", "computed_at"}  # folded away by the dedup, not exposed
# argMax(…, computed_at) columns; expires_at rides along so `expires_at > today()` sees the freshest row.
_LATEST = {"cost", "clicks", "impressions", "reported_conversions", "reported_conversion_value", "expires_at"}
# Full cell identity — always GROUP BY all of it so each cell collapses independently.
_DIMENSIONS = [c for c in _RAW_FIELDS if c not in _INTERNAL | _LATEST | {"timestamp"}]


class MarketingCostsPrecomputedTable(LazyTable):
    description: str = (
        "Deduplicated marketing ad-spend cost rows (per source, campaign, ad group, ad, day). Collapses the "
        "raw `marketing_costs_preaggregated` ReplacingMergeTree to one latest-job row per cell via "
        "argMax(metric, computed_at). Read this instead of the raw table to avoid double-counting."
    )

    fields: dict[str, FieldOrTable] = {
        **{name: field for name, field in _RAW_FIELDS.items() if name not in _INTERNAL | {"timestamp"}},
        # Materialized DateTime so a TrendsQuery DataWarehouseNode can target the view (trends hardcodes `timestamp`).
        "timestamp": DateTimeDatabaseField(name="timestamp"),
    }

    def lazy_select(
        self, table_to_add: LazyTableToAdd, context: HogQLContext, node: ast.SelectQuery
    ) -> ast.SelectQuery:
        requested = table_to_add.fields_accessed

        def raw(col: str) -> ast.Field:
            return ast.Field(chain=[_RAW, col])

        select_fields: list[ast.Expr] = []
        for name in requested:
            if name in _LATEST:
                expr: ast.Expr = ast.Call(name="argMax", args=[raw(name), raw("computed_at")])
            elif name == "timestamp":
                expr = ast.Call(name="toDateTime", args=[raw("cost_date")])
            else:
                expr = raw(name)
            select_fields.append(ast.Alias(alias=name, expr=expr))

        return ast.SelectQuery(
            select=select_fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=["posthog", "marketing_costs_preaggregated"]), alias=_RAW),
            group_by=[raw(dim) for dim in _DIMENSIONS],
        )

    def to_printed_clickhouse(self, context):
        return MARKETING_COSTS_PRECOMPUTED_VIEW_NAME

    def to_printed_hogql(self):
        return MARKETING_COSTS_PRECOMPUTED_VIEW_NAME
