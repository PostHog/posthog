from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.flag_evaluations.sql import (
    DISTRIBUTED_FLAG_EVALUATIONS_JSON_TABLE_SQL,
    FLAG_EVALUATIONS_JSON_MV_SQL,
    FLAG_EVALUATIONS_JSON_TABLE_SQL,
    KAFKA_FLAG_EVALUATIONS_JSON_TABLE_SQL,
    WRITABLE_FLAG_EVALUATIONS_JSON_TABLE_SQL,
)
from posthog.run_mode import run_mode

# Cloud clusters get this schema rolled out separately. Keep this migration empty there so
# merging the application code does not change production ClickHouse schema.
# A self-hosted deployment gets the tables without the consumer, so no personal data lands in a
# table that no deletion sweep reaches yet.
operations = (
    []
    if run_mode().is_deployed_cloud
    else [
        run_sql_with_exceptions(
            FLAG_EVALUATIONS_JSON_TABLE_SQL(),
            node_roles=[NodeRole.DATA],
        ),
        run_sql_with_exceptions(
            DISTRIBUTED_FLAG_EVALUATIONS_JSON_TABLE_SQL(),
            node_roles=[NodeRole.DATA],
        ),
        run_sql_with_exceptions(
            WRITABLE_FLAG_EVALUATIONS_JSON_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        *(
            []
            if run_mode().is_hobby
            else [
                run_sql_with_exceptions(
                    KAFKA_FLAG_EVALUATIONS_JSON_TABLE_SQL(),
                    node_roles=[NodeRole.INGESTION_MEDIUM],
                ),
                run_sql_with_exceptions(
                    FLAG_EVALUATIONS_JSON_MV_SQL(),
                    node_roles=[NodeRole.INGESTION_MEDIUM],
                ),
            ]
        ),
    ]
)
