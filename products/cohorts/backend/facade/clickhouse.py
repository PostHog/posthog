"""The ClickHouse tables core creates and migrates for this product.

Wiring, not data: `posthog/clickhouse/schema.py` builds these in a local or test ClickHouse, and
the migration that created them applies the same definitions to a cluster.
"""

from products.cohorts.backend.models.realtime_cohort_membership_sql import (
    KAFKA_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL as KAFKA_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL,
    REALTIME_COHORT_MEMBERSHIP_MV_SQL as REALTIME_COHORT_MEMBERSHIP_MV_SQL,
    REALTIME_COHORT_MEMBERSHIP_TABLE_SQL as REALTIME_COHORT_MEMBERSHIP_TABLE_SQL,
    TRUNCATE_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL as TRUNCATE_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL,
    WRITABLE_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL as WRITABLE_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL,
)
