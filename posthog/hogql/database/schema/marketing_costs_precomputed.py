from typing import TYPE_CHECKING

import posthoganalytics

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DateTimeDatabaseField, FieldOrTable, LazyTable, LazyTableToAdd
from posthog.hogql.database.schema.marketing_costs_preaggregated import MarketingCostsPreaggregatedTable

if TYPE_CHECKING:
    from posthog.models.team import Team

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
# match_key is a join key re-derived per job from the team's campaign_field_preferences (campaign_name or
# campaign_id), not cell identity — keeping it in the GROUP BY duplicates every cell when the preference
# flips, so the latest job's value wins instead.
_LATEST_LABELS = {"match_key"}
_ARGMAX = _LATEST | _LATEST_LABELS
# Renamable display labels, which split a cell the same way match_key does. Folded only behind the flag, so
# the wider dedup stays reversible without a second view.
_IDENTITY_LABELS = {"campaign_name", "ad_group_name", "ad_name"}

COSTS_DEDUP_V2_FLAG = "marketing-analytics-costs-dedup-v2"
_FLAG_CACHE_ATTR = "_ma_costs_dedup_v2"


def costs_dedup_v2_enabled(team: "Team | None") -> bool:
    """Whether the renamable display labels are folded into argMax alongside the metrics.

    Evaluated locally and cached on the team instance: this sits on the query-compile path, which runs once
    per lazy-table resolution, so a network round trip or a `$feature_flag_called` event per query would be
    a real cost. Falls back to the legacy grouping when the team is unavailable or the flag can't resolve.
    """
    if team is None:
        return False
    cached = getattr(team, _FLAG_CACHE_ATTR, None)
    if cached is not None:
        return cached
    organization = team.organization
    enabled = bool(
        posthoganalytics.feature_enabled(
            COSTS_DEDUP_V2_FLAG,
            str(team.uuid),
            groups={"organization": str(organization.id)},
            group_properties={"organization": {"id": str(organization.id)}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    )
    setattr(team, _FLAG_CACHE_ATTR, enabled)
    return enabled


def _argmax_columns(dedup_labels_by_identity: bool) -> set[str]:
    return _ARGMAX | _IDENTITY_LABELS if dedup_labels_by_identity else _ARGMAX


def _dimension_columns(dedup_labels_by_identity: bool) -> list[str]:
    # Full cell identity — always GROUP BY all of it so each cell collapses independently.
    argmax = _argmax_columns(dedup_labels_by_identity)
    return [c for c in _RAW_FIELDS if c not in _INTERNAL | argmax | {"timestamp"}]


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
        dedup_labels_by_identity = costs_dedup_v2_enabled(context.team)
        argmax = _argmax_columns(dedup_labels_by_identity)
        dimensions = _dimension_columns(dedup_labels_by_identity)

        def raw(col: str) -> ast.Field:
            return ast.Field(chain=[_RAW, col])

        select_fields: list[ast.Expr] = []
        for name in requested:
            if name in argmax:
                expr: ast.Expr = ast.Call(name="argMax", args=[raw(name), raw("computed_at")])
            elif name == "timestamp":
                expr = ast.Call(name="toDateTime", args=[raw("cost_date")])
            else:
                expr = raw(name)
            select_fields.append(ast.Alias(alias=name, expr=expr))

        return ast.SelectQuery(
            select=select_fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=["posthog", "marketing_costs_preaggregated"]), alias=_RAW),
            group_by=[raw(dim) for dim in dimensions],
        )

    def to_printed_clickhouse(self, context):
        return MARKETING_COSTS_PRECOMPUTED_VIEW_NAME

    def to_printed_hogql(self):
        return MARKETING_COSTS_PRECOMPUTED_VIEW_NAME
