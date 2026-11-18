"""The ClickHouse tables core creates and migrates for this product.

Wiring, not data: `posthog/clickhouse/schema.py` builds these in a local or test ClickHouse, and
the migration that created them applies the same definitions to a cluster.
"""

from products.alerts_platform.backend.models.platform_alert_events_sql import (
    DISTRIBUTED_PLATFORM_ALERT_EVENTS_TABLE_SQL as DISTRIBUTED_PLATFORM_ALERT_EVENTS_TABLE_SQL,
    PLATFORM_ALERT_EVENTS_TABLE as PLATFORM_ALERT_EVENTS_TABLE,
    SHARDED_PLATFORM_ALERT_EVENTS_TABLE as SHARDED_PLATFORM_ALERT_EVENTS_TABLE,
    SHARDED_PLATFORM_ALERT_EVENTS_TABLE_SQL as SHARDED_PLATFORM_ALERT_EVENTS_TABLE_SQL,
)
