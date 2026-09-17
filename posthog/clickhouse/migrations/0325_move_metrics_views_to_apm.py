from pathlib import Path

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.run_mode import run_mode

SQL_DIR = Path(__file__).parent / "sql" / "0325"

APM_TABLES = (
    "kafka_metrics_avro2",
    "metrics2_input",
    "writable_metrics2",
    "writable_metric_series2",
    "writable_metric_attributes2",
    "writable_metric_series3",
    "writable_metric_attributes3",
    "writable_metric_names3",
)

DOWNSTREAM_VIEWS = (
    "metrics2_input_to_metrics",
    "metrics2_input_to_metric_series",
    "metrics2_input_to_metric_attributes",
    "metrics2_input_to_resource_attributes",
    "metrics2_input_to_metric_names3",
    "metrics2_input_to_metric_series3",
    "metrics2_input_to_metric_attributes3",
    "metrics2_input_to_resource_attributes3",
)

LEGACY_VIEWS = (
    "kafka_metrics_avro_mv",
    "kafka_metrics_avro_to_metric_samples",
    "kafka_metrics_avro_to_metric_series",
    "kafka_metrics_avro_kafka_metrics_mv",
    "metrics1_to_metric_attributes",
    "metrics1_to_resource_attributes",
)

operations = []

if run_mode().is_deployed_cloud:
    operations.extend(
        run_sql_with_exceptions(
            (SQL_DIR / f"{table}.sql").read_text(),
            node_roles=[NodeRole.INGESTION_APM],
            require_hosts=True,
        )
        for table in APM_TABLES
    )
    operations.append(
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS posthog.kafka_metrics_avro2_mv SYNC",
            node_roles=[NodeRole.INGESTION_APM],
            require_hosts=True,
        )
    )
    for view in DOWNSTREAM_VIEWS:
        operations.extend(
            [
                run_sql_with_exceptions(
                    f"DROP TABLE IF EXISTS posthog.{view} SYNC",
                    node_roles=[NodeRole.INGESTION_APM],
                    require_hosts=True,
                ),
                run_sql_with_exceptions(
                    (SQL_DIR / f"{view}.sql").read_text(),
                    node_roles=[NodeRole.INGESTION_APM],
                    require_hosts=True,
                ),
            ]
        )
    operations.append(
        run_sql_with_exceptions(
            (SQL_DIR / "kafka_metrics_avro2_mv.sql").read_text(),
            node_roles=[NodeRole.INGESTION_APM],
            require_hosts=True,
        )
    )
    operations.extend(
        run_sql_with_exceptions(
            f"DROP TABLE IF EXISTS posthog.{view} SYNC",
            node_roles=[NodeRole.LOGS],
        )
        for view in ("kafka_metrics_avro2_mv", *LEGACY_VIEWS, *DOWNSTREAM_VIEWS)
    )
