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

    def insert_events(client: Client) -> None:
        client.execute(
            "INSERT INTO writable_events (distinct_id, person_id, timestamp) VALUES",
            [
                ("a", UUID(int=0), timestamp - timedelta(hours=24)),
                ("b", UUID(int=1), timestamp - timedelta(hours=24)),
                ("c", UUID(int=2), timestamp - timedelta(hours=24)),
                ("d", UUID(int=3), timestamp - timedelta(hours=12)),
                ("e", UUID(int=4), timestamp - timedelta(hours=6)),
                ("z", UUID(int=100), timestamp - timedelta(hours=3)),
            ],
        )

    cluster.any_host(insert_events).result()

    def insert_overrides(client: Client) -> None:
        client.execute(
            "INSERT INTO person_distinct_id_overrides (distinct_id, person_id, _timestamp, version) VALUES",
            [
                ("c", UUID(int=0), timestamp - timedelta(hours=12), 1),  # 0: {"a", "c"}
                ("e", UUID(int=3), timestamp - timedelta(hours=6), 1),  # 3: {"d", "e"}
                ("d", UUID(int=1), timestamp - timedelta(hours=5), 1),  # 1: {"b", "d"}
                ("e", UUID(int=1), timestamp - timedelta(hours=5), 2),  # 1: {"b", "d", "e"}
                ("z", UUID(int=0), timestamp + timedelta(hours=1), 1),  # arrived after timestamp, ignored this run
            ],
        )

    cluster.any_host(insert_overrides).result()

    def get_distinct_ids_on_events_by_person(client: Client) -> dict[UUID, int]:
        rows = client.execute("SELECT person_id, groupUniqArray(distinct_id) FROM events GROUP BY ALL")
        result = {person_id: set(distinct_ids) for person_id, distinct_ids in rows}
        assert len(rows) == len(result)
        return result

    def get_distinct_ids_with_overrides(client: Client) -> set[str]:
        rows = client.execute("SELECT distinct_id FROM person_distinct_id_overrides FINAL")
        result = {distinct_id for [distinct_id] in rows}
        assert len(rows) == len(result)
        return result

    # check preconditions
    assert cluster.any_host(get_distinct_ids_on_events_by_person).result() == {
        UUID(int=0): {"a"},
        UUID(int=1): {"b"},
        UUID(int=2): {"c"},
        UUID(int=3): {"d"},
        UUID(int=4): {"e"},
        UUID(int=100): {"z"},
    }
    assert cluster.any_host(get_distinct_ids_with_overrides).result() == {"c", "d", "e", "z"}

    result = squash_person_overrides.execute_in_process(
        run_config=dagster.RunConfig(
            {create_snapshot_table.name: SnapshotTableConfig(timestamp=timestamp.isoformat())}
        ),
        resources={"cluster": cluster},
    )

    # check postconditions
    assert cluster.any_host(get_distinct_ids_on_events_by_person).result() == {
        UUID(int=0): {"a", "c"},
        UUID(int=1): {"b", "d", "e"},
        UUID(int=100): {"z"},
    }
    assert cluster.any_host(get_distinct_ids_with_overrides).result() == {"z"}

    # ensure we cleaned up after ourselves
    table = PersonOverridesSnapshotTable(UUID(result.dagster_run.run_id), timestamp)
    dictionary = PersonOverridesSnapshotDictionary(table)
    assert not any(cluster.map_all_hosts(table.exists).result().values())
    assert not any(cluster.map_all_hosts(dictionary.exists).result().values())
