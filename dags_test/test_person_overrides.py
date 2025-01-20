from collections.abc import Iterator
from datetime import datetime, timedelta
from uuid import UUID

import dagster
import pytest
from clickhouse_driver import Client

from dags.person_overrides import (
    PersonOverridesSnapshotDictionary,
    PersonOverridesSnapshotTable,
    SnapshotTableConfig,
    create_snapshot_table,
    squash_person_overrides,
)
from ee.clickhouse.materialized_columns.columns import get_cluster  # XXX
from posthog.clickhouse.cluster import ClickhouseCluster


@pytest.fixture
def cluster(django_db_setup) -> Iterator[ClickhouseCluster]:
    yield get_cluster()


def test_full_job(cluster: ClickhouseCluster):
    timestamp = datetime(2025, 1, 1)

    events = [
        ("a", UUID(int=0), timestamp - timedelta(hours=24)),
        ("b", UUID(int=1), timestamp - timedelta(hours=24)),
        ("c", UUID(int=2), timestamp - timedelta(hours=24)),
        ("d", UUID(int=4), timestamp - timedelta(hours=24)),
    ]

    def insert_events(client: Client) -> None:
        client.execute("INSERT INTO writable_events (distinct_id, person_id, timestamp) VALUES", events)

    cluster.any_host(insert_events).result()

    # TODO: also test a multiple-version merge
    overrides = [
        ("c", UUID(int=0), timestamp - timedelta(hours=12), 1),
        ("d", UUID(int=1), timestamp + timedelta(hours=1), 1),
    ]

    def insert_overrides(client: Client) -> None:
        client.execute(
            "INSERT INTO person_distinct_id_overrides (distinct_id, person_id, _timestamp, version) VALUES", overrides
        )

    cluster.any_host(insert_overrides).result()

    result = squash_person_overrides.execute_in_process(
        run_config=dagster.RunConfig(
            {create_snapshot_table.name: SnapshotTableConfig(timestamp=timestamp.isoformat())}
        ),
        resources={"cluster": cluster},
    )

    # ensure we cleaned up after ourselves
    table = PersonOverridesSnapshotTable(UUID(result.dagster_run.run_id), timestamp)
    dictionary = PersonOverridesSnapshotDictionary(table)
    assert not any(cluster.map_all_hosts(table.exists).result().values())
    assert not any(cluster.map_all_hosts(dictionary.exists).result().values())
