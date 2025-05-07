from dags.property_definitions import property_definitions_ingestion_job
from posthog.clickhouse.cluster import ClickhouseCluster


def test_ingestion_job(cluster: ClickhouseCluster) -> None:
    property_definitions_ingestion_job.execute_in_process(
        resources={"cluster": cluster},
    )
