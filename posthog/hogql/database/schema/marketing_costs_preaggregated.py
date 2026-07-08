from pydantic import Field

from posthog.hogql import ast
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.database.models import (
    DateDatabaseField,
    DateTimeDatabaseField,
    ExpressionField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

from posthog.clickhouse.preaggregation.marketing_costs_sql import DISTRIBUTED_MARKETING_COSTS_TABLE


class MarketingCostsPreaggregatedTable(Table):
    description: str = (
        "Internal preaggregated table of marketing ad-spend cost rows (per source, campaign, ad group, ad, day) "
        "materialized from external data-warehouse tables into native ClickHouse for the marketing analytics dashboard."
    )
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order")
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(
            name="job_id", description="Identifier of the preaggregation job that produced this row."
        ),
        "source_id": StringDatabaseField(
            name="source_id",
            description="Identifier of the marketing source (data warehouse source) the cost came from.",
        ),
        "source_name": StringDatabaseField(
            name="source_name", description="Human-readable name of the marketing source (e.g. 'Google Ads')."
        ),
        "grain": StringDatabaseField(
            name="grain", description="Granularity level of this cost row (e.g. campaign, ad_group, or ad)."
        ),
        "match_key": StringDatabaseField(
            name="match_key", description="Key used to match cost rows against touchpoints/conversions for attribution."
        ),
        "campaign_id": StringDatabaseField(name="campaign_id", description="Source campaign identifier."),
        "campaign_name": StringDatabaseField(name="campaign_name", description="Source campaign name."),
        "ad_group_id": StringDatabaseField(name="ad_group_id", description="Source ad group identifier."),
        "ad_group_name": StringDatabaseField(name="ad_group_name", description="Source ad group name."),
        "ad_id": StringDatabaseField(name="ad_id", description="Source ad identifier."),
        "ad_name": StringDatabaseField(name="ad_name", description="Source ad name."),
        "cost_date": DateDatabaseField(name="cost_date", description="Date the cost was incurred."),
        "cost": FloatDatabaseField(
            name="cost", description="Ad spend for this row, in the source's reporting currency."
        ),
        "clicks": FloatDatabaseField(
            name="clicks", description="Number of clicks reported by the source for this row."
        ),
        "impressions": FloatDatabaseField(
            name="impressions", description="Number of impressions reported by the source for this row."
        ),
        "reported_conversions": FloatDatabaseField(
            name="reported_conversions",
            description="Conversions reported by the ad source itself (not PostHog-attributed).",
        ),
        "reported_conversion_value": FloatDatabaseField(
            name="reported_conversion_value", description="Conversion value reported by the ad source itself."
        ),
        "computed_at": DateTimeDatabaseField(
            name="computed_at",
            description="When this preaggregated row was computed; also the ReplacingMergeTree version.",
        ),
        "expires_at": DateDatabaseField(
            name="expires_at", description="Date when this row expires and is dropped via TTL."
        ),
        # Virtual `timestamp` lets a TrendsQuery DataWarehouseNode target this native table — the trends
        # builder references a hardcoded `timestamp` field. cost_date is a Date; expose it as a DateTime.
        "timestamp": ExpressionField(
            name="timestamp",
            expr=ast.Call(name="toDateTime", args=[ast.Field(chain=["cost_date"])]),
            isolate_scope=True,
        ),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_MARKETING_COSTS_TABLE()

    def to_printed_hogql(self):
        return "marketing_costs_preaggregated"
