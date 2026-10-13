from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.precalculated_events.sql import (
    DROP_PRECALCULATED_EVENTS_WS_KAFKA_TABLE_SQL,
    DROP_PRECALCULATED_EVENTS_WS_MV_SQL,
)
from posthog.models.precalculated_person_properties.sql import (
    DROP_PRECALCULATED_PERSON_PROPERTIES_WS_KAFKA_TABLE_SQL,
    DROP_PRECALCULATED_PERSON_PROPERTIES_WS_MV_SQL,
)

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
# Both pairs were created unconditionally by 0229, so both drops are unconditional. 0243
# then dropped the events pair everywhere and recreated it cloud-only, because off-cloud
# the `warpstream_calculated_events` collection resolves to the same brokers as
# `msk_cluster` and the pair double-writes. It left
# `kafka_precalculated_person_properties_ws` behind, which this drop finally removes.
#
# `kafka_cohort_membership_ws` reads from the same collection but is deliberately left
# in place here; it is dropped separately.
#
# Only the Kafka engine tables and their MVs go. The `precalculated_events` and
# `precalculated_person_properties` data tables stay, as do the MSK-fed Kafka tables that
# do not resolve this named collection.

operations = [
    run_sql_with_exceptions(
        DROP_PRECALCULATED_EVENTS_WS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        DROP_PRECALCULATED_EVENTS_WS_KAFKA_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        DROP_PRECALCULATED_PERSON_PROPERTIES_WS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        DROP_PRECALCULATED_PERSON_PROPERTIES_WS_KAFKA_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
]
