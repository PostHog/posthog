from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Drop the two precalculated Kafka engine tables bound to the
# `warpstream_calculated_events` named collection, on the way to decommissioning that
# cluster:
#
#   clickhouse_prefiltered_events               -> kafka_precalculated_events_ws
#   clickhouse_precalculated_person_properties  -> kafka_precalculated_person_properties_ws
#
# On cloud neither topic has a producer any more, so all four objects read nothing.
# They have to go before the named collection is removed from the ClickHouse config: a
# Kafka engine table whose named collection has disappeared error-loops on every poll.
#
# Within each pair the MV is dropped first so it stops feeding its writable table, then
# the Kafka engine table.
#
# Both drops are unconditional. Installs that created the person properties pair in 0229
# still have it, and cloud installs that recreated the events pair in 0243 still have that one.
#
# `kafka_cohort_membership_ws` reads from the same collection but is deliberately left
# in place here; it is dropped separately.
#
# Only the Kafka engine tables and their MVs go. The `precalculated_events` and
# `precalculated_person_properties` data tables stay, as do the MSK-fed Kafka tables that
# do not resolve this named collection.

operations = [
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS precalculated_events_ws_mv",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS kafka_precalculated_events_ws",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS precalculated_person_properties_ws_mv",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS kafka_precalculated_person_properties_ws",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
]
