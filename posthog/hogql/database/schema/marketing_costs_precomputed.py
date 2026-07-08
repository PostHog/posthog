from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DateTimeDatabaseField, FieldOrTable, LazyTable, LazyTableToAdd
from posthog.hogql.database.schema.marketing_costs_preaggregated import MarketingCostsPreaggregatedTable

# Public, deduplicated read interface over `marketing_costs_preaggregated`. The raw table is a
# ReplacingMergeTree whose sort key includes `job_id`, so the same cost cell (source/campaign/ad/day)
# survives as several rows when it is re-materialized (a matured day the source revised, a
# double-triggered job, or a compare period reusing a wider window). A bare `SUM` over the raw table
# double-counts those. This view collapses each cell to its latest job via `argMax(metric, computed_at)`
# (computed_at is the ReplacingMergeTree version), so every reader — the dashboard table, the trend
# charts, and any future insight — gets one correct row per cell without re-implementing the dedup.
# Treat the raw `*_preaggregated` table as private to the materializer; read this instead.
#
# Named `_precomputed`, not a bare `marketing_costs`, on purpose: it holds only what the precompute
# materialized, so sources that fall back to live S3 are absent. It is the precomputed subset, not the
# complete/authoritative set of marketing costs — the name warns a reader not to treat it as complete.

MARKETING_COSTS_PRECOMPUTED_VIEW_NAME = "marketing_costs_precomputed"

# Alias for the inner raw table reference, so field chains inside the subquery stay two-element.
_RAW = "marketing_costs_preaggregated"

# Reuse the raw table's column definitions so the view can't drift from the schema it reads.
_RAW_FIELDS = MarketingCostsPreaggregatedTable().fields
# Internal columns the dedup folds away — never exposed by the view.
_INTERNAL = {"job_id", "computed_at"}
# Metrics take the latest job's value via argMax(…, computed_at). `expires_at` rides along so a consumer's
# `expires_at > today()` filter reflects the freshest row's TTL, not an arbitrary duplicate's.
_LATEST = {"cost", "clicks", "impressions", "reported_conversions", "reported_conversion_value", "expires_at"}
# Cell identity: every exposed column that isn't a metric or the virtual timestamp. We GROUP BY all of these
# on every read (regardless of which columns the caller selected) so each cell collapses independently — a
# partial GROUP BY would fold unrelated cells together and argMax the wrong row.
_DIMENSIONS = [c for c in _RAW_FIELDS if c not in _INTERNAL | _LATEST | {"timestamp"}]


class MarketingCostsPrecomputedTable(LazyTable):
    description: str = (
        "Deduplicated marketing ad-spend cost rows (per source, campaign, ad group, ad, day). Collapses the "
        "raw `marketing_costs_preaggregated` ReplacingMergeTree to one latest-job row per cell via "
        "argMax(metric, computed_at). Read this instead of the raw table to avoid double-counting."
    )

    fields: dict[str, FieldOrTable] = {
        **{name: field for name, field in _RAW_FIELDS.items() if name not in _INTERNAL | {"timestamp"}},
        # Materialized DateTime (lazy_select emits toDateTime(cost_date)) so a TrendsQuery DataWarehouseNode
        # can target the view — the trends builder references a hardcoded `timestamp` field.
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
