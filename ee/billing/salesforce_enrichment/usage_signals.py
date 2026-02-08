"""Usage signals aggregation for Salesforce enrichment - reads from organization group properties."""

from dataclasses import dataclass, field

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import query_with_columns
from posthog.clickhouse.query_tagging import tags_context
from posthog.temporal.common.logger import get_logger

LOGGER = get_logger(__name__)


@dataclass
class UsageSignals:
    """Usage signals for an organization - read from group properties."""

    # Events-based metrics (7-day)
    total_events_7d: int = 0
    events_avg_daily_7d: float | None = None
    products_activated_7d: list[str] = field(default_factory=list)
    events_7d_momentum: float | None = None

    # Events-based metrics (30-day)
    total_events_30d: int = 0
    events_avg_daily_30d: float | None = None
    products_activated_30d: list[str] = field(default_factory=list)
    events_30d_momentum: float | None = None


def fetch_usage_signals_from_groups(org_ids: list[str]) -> dict[str, dict]:
    """Fetch usage signals from organization group properties.

    The group properties are set by billing_usagereport and contain pre-computed
    usage metrics for each organization.
    """
    if not org_ids:
        return {}

    query = """
        SELECT
            group_key as org_id,
            JSONExtractInt(group_properties, 'usage_events_7d') as events_7d,
            JSONExtractFloat(group_properties, 'usage_events_avg_daily_7d') as events_avg_daily_7d,
            JSONExtractString(group_properties, 'usage_products_7d') as products_7d,
            JSONExtractInt(group_properties, 'usage_events_30d') as events_30d,
            JSONExtractFloat(group_properties, 'usage_events_avg_daily_30d') as events_avg_daily_30d,
            JSONExtractString(group_properties, 'usage_products_30d') as products_30d,
            JSONExtractFloat(group_properties, 'usage_events_7d_momentum') as events_7d_momentum,
            JSONExtractFloat(group_properties, 'usage_events_30d_momentum') as events_30d_momentum
        FROM groups FINAL
        WHERE group_type_index = 0
          AND group_key IN %(org_ids)s
          AND notEmpty(JSONExtractString(group_properties, 'usage_signals_computed_at'))
    """

    with tags_context(usage_report="salesforce_usage_signals"):
        results = query_with_columns(query, {"org_ids": org_ids}, workload=Workload.OFFLINE)

    def parse_products(products_str: str) -> list[str]:
        """Parse comma-separated products string into a list."""
        return [p.strip() for p in products_str.split(",") if p.strip()] if products_str else []

    return {
        row["org_id"]: {
            "total_events_7d": row["events_7d"] or 0,
            "events_avg_daily_7d": row["events_avg_daily_7d"],
            "products_activated_7d": parse_products(row["products_7d"]),
            "total_events_30d": row["events_30d"] or 0,
            "events_avg_daily_30d": row["events_avg_daily_30d"],
            "products_activated_30d": parse_products(row["products_30d"]),
            "events_7d_momentum": row["events_7d_momentum"],
            "events_30d_momentum": row["events_30d_momentum"],
        }
        for row in results
    }


def aggregate_usage_signals_for_orgs(org_ids: list[str]) -> dict[str, UsageSignals]:
    """Aggregate usage signals from group properties for organizations."""
    if not org_ids:
        return {}

    LOGGER.info("fetching_usage_signals_from_groups", org_count=len(org_ids))
    group_signals = fetch_usage_signals_from_groups(org_ids)

    result = {}
    for org_id in org_ids:
        gs = group_signals.get(org_id, {})
        result[org_id] = UsageSignals(
            total_events_7d=gs.get("total_events_7d", 0),
            events_avg_daily_7d=gs.get("events_avg_daily_7d"),
            products_activated_7d=gs.get("products_activated_7d", []),
            events_7d_momentum=gs.get("events_7d_momentum"),
            total_events_30d=gs.get("total_events_30d", 0),
            events_avg_daily_30d=gs.get("events_avg_daily_30d"),
            products_activated_30d=gs.get("products_activated_30d", []),
            events_30d_momentum=gs.get("events_30d_momentum"),
        )

    LOGGER.info("fetched_usage_signals", org_count=len(org_ids), signals_found=len(group_signals))
    return result
