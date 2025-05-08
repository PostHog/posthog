import dagster

from dags.property_definitions import PropertyDefinitionsConfig, property_definitions_ingestion_job
from posthog.clickhouse.cluster import ClickhouseCluster


def test_ingestion_job(cluster: ClickhouseCluster) -> None:
    config = PropertyDefinitionsConfig(start_at="2025-05-07T00:00:00", duration="1 hour")
    property_definitions_ingestion_job.execute_in_process(
        run_config=dagster.RunConfig({"setup_job": config}),
        resources={"cluster": cluster},
    )
