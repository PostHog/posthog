from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.finops.usage_meters import (
    DISTRIBUTED_FINOPS_USAGE_METERS_TABLE_SQL,
    FINOPS_USAGE_METERS_MV_SQL,
    KAFKA_FINOPS_USAGE_METERS_TABLE_SQL,
    SHARDED_FINOPS_USAGE_METERS_TABLE_SQL,
    WRITABLE_FINOPS_USAGE_METERS_TABLE_SQL,
)

operations = [
    # 1. Sharded data table on the AUX cluster — kept off the customer-facing analytics path.
    run_sql_with_exceptions(
        SHARDED_FINOPS_USAGE_METERS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    # 2. Distributed read proxy on data nodes so queries can fan out to AUX.
    run_sql_with_exceptions(
        DISTRIBUTED_FINOPS_USAGE_METERS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # 3. Writable distributed table on the ingestion layer — the MV writes here, rows route to AUX.
    run_sql_with_exceptions(
        WRITABLE_FINOPS_USAGE_METERS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 4. Dedicated Kafka engine table — own topic + consumer group, own failure domain.
    run_sql_with_exceptions(
        KAFKA_FINOPS_USAGE_METERS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 5. MV projecting the Kafka stream into the writable table.
    run_sql_with_exceptions(
        FINOPS_USAGE_METERS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]
