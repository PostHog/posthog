from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.cohortmembership.sql import (
    DROP_COHORT_MEMBERSHIP_WS_KAFKA_TABLE_SQL,
    DROP_COHORT_MEMBERSHIP_WS_MV_SQL,
)
from posthog.models.precalculated_events.sql import (
    DROP_PRECALCULATED_EVENTS_WS_KAFKA_TABLE_SQL,
    DROP_PRECALCULATED_EVENTS_WS_MV_SQL,
)
from posthog.models.precalculated_person_properties.sql import (
    DROP_PRECALCULATED_PERSON_PROPERTIES_WS_KAFKA_TABLE_SQL,
    DROP_PRECALCULATED_PERSON_PROPERTIES_WS_MV_SQL,
)

# Drop every Kafka engine table bound to the `warpstream_calculated_events` named
# collection, so that cluster can be decommissioned.
#
# It carries three topics, each with a `_ws` Kafka engine table and MV:
#
#   clickhouse_prefiltered_events               -> kafka_precalculated_events_ws
#   clickhouse_precalculated_person_properties  -> kafka_precalculated_person_properties_ws
#   cohort_membership_changed                   -> kafka_cohort_membership_ws
#
# On cloud none of the three topics has a producer any more, so all six objects read
# nothing. Off-cloud the person-properties pair still consumes the local topic (see below).
# They have to go before the named collection is removed from the ClickHouse config: a
# Kafka engine table whose named collection has disappeared error-loops on every poll.
#
# Within each pair the MV is dropped first so it stops feeding its writable table, then
# the Kafka engine table.
#
# The guards differ because the creating migrations differed. Both precalculated pairs
# were created unconditionally by 0229, so they are dropped unconditionally. 0243 then
# dropped the events pair everywhere and recreated it cloud-only, because off-cloud the
# `warpstream_calculated_events` collection resolves to the same brokers as `msk_cluster`
# and the pair double-writes. It left `kafka_precalculated_person_properties_ws` behind,
# which this drop finally removes. `kafka_cohort_membership_ws` was created cloud-only by
# 0245, so its drop keeps that guard.
#
# Only the Kafka engine tables and their MVs go. The `precalculated_events`,
# `precalculated_person_properties` and `cohort_membership` data tables stay, as do the
# MSK-fed Kafka tables that do not resolve this named collection.

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
] + (
    []
    if settings.CLOUD_DEPLOYMENT not in ("US", "EU", "DEV")
    else [
        run_sql_with_exceptions(
            DROP_COHORT_MEMBERSHIP_WS_MV_SQL(),
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        run_sql_with_exceptions(
            DROP_COHORT_MEMBERSHIP_WS_KAFKA_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
    ]
)
