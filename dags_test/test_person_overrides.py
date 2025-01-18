import uuid
import dagster
import pytest

from dags.person_overrides import (
    SnapshotTableConfig,
    squash_person_overrides,
    PersonOverridesSnapshotDictionary,
    PersonOverridesSnapshotTable,
)
from ee.clickhouse.materialized_columns.columns import get_cluster  # XXX
from posthog.clickhouse.cluster import ClickhouseCluster


@pytest.fixture
def cluster(django_db_setup) -> ClickhouseCluster:
    yield get_cluster()


def test_job(cluster):
    timestamp = "2025-01-01"
    result = squash_person_overrides.execute_in_process(
        run_config=dagster.RunConfig({"create_snapshot_table": SnapshotTableConfig(timestamp=timestamp)}),
        resources={"cluster": cluster},
    )

    # ensure we cleaned up after ourselves
    table = PersonOverridesSnapshotTable(uuid.UUID(result.dagster_run.run_id), timestamp)
    dictionary = PersonOverridesSnapshotDictionary(table)
    assert not any(cluster.map_all_hosts(table.exists).result().values())
    assert not any(cluster.map_all_hosts(dictionary.exists).result().values())
