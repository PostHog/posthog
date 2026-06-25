from pydantic import Field

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.database.models import (
    DateDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

from posthog.clickhouse.preaggregation.marketing_costs_sql import DISTRIBUTED_MARKETING_COSTS_TABLE


class MarketingCostsPreaggregatedTable(Table):
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order")
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(name="job_id"),
        "source_id": StringDatabaseField(name="source_id"),
        "source_name": StringDatabaseField(name="source_name"),
        "grain": StringDatabaseField(name="grain"),
        "match_key": StringDatabaseField(name="match_key"),
        "campaign_id": StringDatabaseField(name="campaign_id"),
        "campaign_name": StringDatabaseField(name="campaign_name"),
        "ad_group_id": StringDatabaseField(name="ad_group_id"),
        "ad_group_name": StringDatabaseField(name="ad_group_name"),
        "ad_id": StringDatabaseField(name="ad_id"),
        "ad_name": StringDatabaseField(name="ad_name"),
        "cost_date": DateDatabaseField(name="cost_date"),
        "cost": FloatDatabaseField(name="cost"),
        "clicks": FloatDatabaseField(name="clicks"),
        "impressions": FloatDatabaseField(name="impressions"),
        "reported_conversions": FloatDatabaseField(name="reported_conversions"),
        "reported_conversion_value": FloatDatabaseField(name="reported_conversion_value"),
        "computed_at": DateTimeDatabaseField(name="computed_at"),
        "expires_at": DateDatabaseField(name="expires_at"),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_MARKETING_COSTS_TABLE()

    def to_printed_hogql(self):
        return "marketing_costs_preaggregated"
