import dagster
import pytest

from dags.person_overrides import SnapshotTableConfig, squash_person_overrides
from ee.clickhouse.materialized_columns.columns import get_cluster  # XXX
from posthog.clickhouse.cluster import ClickhouseCluster


@pytest.fixture
def cluster(django_db_setup) -> ClickhouseCluster:
    yield get_cluster()


def test_job(cluster):
    squash_person_overrides.execute_in_process(
        run_config=dagster.RunConfig({"create_snapshot_table": SnapshotTableConfig(timestamp="2025-01-01")}),
        resources={"cluster": cluster},
    )
