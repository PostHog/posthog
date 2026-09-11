import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from django.test import override_settings

from clickhouse_driver import Client

from posthog.clickhouse.adhoc_events_deletion import ADHOC_EVENTS_DELETION_TABLE_SQL
from posthog.clickhouse.cluster import ClickhouseCluster, NodeRole
from posthog.dags.deletes import deletes_job
from posthog.models.event.sql import (
    DISTRIBUTED_EVENTS_JSON_TABLE_SQL,
    DISTRIBUTED_EVENTS_TABLE_SQL,
    EVENTS_DATA_TABLE,
    EVENTS_JSON_DATA_TABLE,
    EVENTS_JSON_TABLE_SQL,
    EVENTS_TABLE_SQL,
)
from posthog.models.person.sql import PERSON_DISTINCT_ID_OVERRIDES_TABLE
from posthog.storage import object_storage

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.timeout(180, func_only=True),
    pytest.mark.skipif(os.getenv("TEST_MULTINODE_DELETES") != "1", reason="Requires docker-compose.deletes-test.yml"),
]


@pytest.fixture
def deletion_nodes(settings) -> Iterator[tuple[ClickhouseCluster, list[Client]]]:
    settings.CLICKHOUSE_ENABLE_STORAGE_POLICY = False
    settings.DICTIONARY_STAGING_S3_PREFIX = f"deletes_multinode/{uuid4()}"
    settings.CLICKHOUSE_EVENTS_CLUSTER = "delete_test_events"
    settings.DICTIONARY_STAGING_S3_ENDPOINT = "http://127.0.0.1:19000"
    clients = [
        Client("127.0.0.1", port=port, settings={"mutations_sync": 1, "lightweight_deletes_sync": 1})
        for port in (19101, 19102, 19103)
    ]
    database = settings.CLICKHOUSE_DATABASE
    created = []
    try:
        for client in clients:
            client.execute(f"CREATE DATABASE {database}")
            created.append(client)
            client.execute(f"USE {database}")
        data, *events = clients
        data.execute(EVENTS_TABLE_SQL())
        with override_settings(CLICKHOUSE_CLUSTER="delete_test_data"):
            data.execute(DISTRIBUTED_EVENTS_TABLE_SQL(on_cluster=False))
        data.execute(
            f"CREATE TABLE {PERSON_DISTINCT_ID_OVERRIDES_TABLE} (_timestamp DateTime) ENGINE = MergeTree ORDER BY tuple()"
        )
        data.execute(ADHOC_EVENTS_DELETION_TABLE_SQL(on_cluster=False))
        for client in events:
            client.execute(EVENTS_JSON_TABLE_SQL())
            with override_settings(CLICKHOUSE_CLUSTER="delete_test_events"):
                client.execute(DISTRIBUTED_EVENTS_JSON_TABLE_SQL(on_cluster=False))
        cluster = ClickhouseCluster(
            data,
            cluster="delete_test_data",
            client_settings={"mutations_sync": "0", "lightweight_deletes_sync": "0"},
            connection_overrides={"user": "default", "password": "", "secure": False},
        )
        yield cluster, clients
    finally:
        for client in created:
            client.execute(f"DROP DATABASE {database} SYNC")
        for client in clients:
            client.disconnect()
        staged = object_storage.list_objects(
            settings.DICTIONARY_STAGING_S3_PREFIX + "/", bucket=settings.DICTIONARY_STAGING_S3_BUCKET
        )
        if staged:
            object_storage.delete_objects(staged, bucket=settings.DICTIONARY_STAGING_S3_BUCKET)


def test_adhoc_deletes_reach_every_events_shard(deletion_nodes):
    cluster, clients = deletion_nodes
    data, *event_nodes = clients
    timestamp = datetime.now(UTC)
    queued = [(101, UUID(int=1)), (101, UUID(int=2))]
    controls = {(101, UUID(int=3)), (202, UUID(int=1))}
    rows = [
        (team, event_uuid, timestamp, "deletion_test_event", f"distinct_{team}_{event_uuid.int}", UUID(int=team))
        for team, event_uuid in [*queued, *sorted(controls)]
    ]

    def event_tables(client):
        return {
            row[0]
            for row in client.execute(
                "SELECT name FROM system.tables WHERE database = currentDatabase() AND name IN %(tables)s",
                {"tables": ("events", EVENTS_DATA_TABLE(), "events_json", EVENTS_JSON_DATA_TABLE)},
            )
        }

    assert data.execute("SELECT getMacro('hostClusterRole')") == [("data",)]
    assert event_tables(data) == {"events", EVENTS_DATA_TABLE()}
    assert len(cluster.shards) == 1
    assert len(cluster.sibling("delete_test_events", NodeRole.EVENTS).shards) == 2
    for shard_index, client in enumerate(event_nodes):
        assert client.execute("SELECT getMacro('hostClusterRole')") == [("events",)]
        assert event_tables(client) == {"events_json", EVENTS_JSON_DATA_TABLE}
        assert client.execute("EXISTS TABLE adhoc_events_deletion") == [(0,)]
        client.execute(
            f"INSERT INTO {EVENTS_JSON_DATA_TABLE} (team_id, uuid, timestamp, event, distinct_id, person_id) VALUES",
            rows[shard_index::2],
        )
    data.execute(
        f"INSERT INTO {EVENTS_DATA_TABLE()} (team_id, uuid, timestamp, event, distinct_id, person_id) VALUES",
        rows,
    )
    data.execute("INSERT INTO adhoc_events_deletion (team_id, uuid) VALUES", queued)

    def survivors(client, table):
        return set(client.execute(f"SELECT team_id, uuid FROM {table} WHERE _row_exists = 1"))

    for shard_index, client in enumerate(event_nodes):
        assert survivors(client, EVENTS_JSON_DATA_TABLE) == {(row[0], row[1]) for row in rows[shard_index::2]}

    def read_events(client, table):
        return client.execute(
            f"SELECT team_id, uuid, timestamp, event, distinct_id, person_id FROM {table} ORDER BY team_id, uuid"
        )

    before = read_events(data, "events")
    for client in event_nodes:
        assert before == read_events(client, "events_json")
    assert before == sorted(rows, key=lambda row: (row[0], row[1]))

    result = deletes_job.execute_in_process(
        resources={"cluster": cluster},
        run_config={
            "ops": {
                name: {"config": {"shards": 1, "dictionary_load_timeout": 30}}
                for name in ("create_deletes_dict", "create_adhoc_event_deletes_dict")
            }
        },
    )

    assert result.success
    assert set(data.execute("SELECT team_id, uuid FROM adhoc_events_deletion WHERE is_deleted = 1")) == set(queued)
    after_events = read_events(data, "events")
    for client in event_nodes:
        assert after_events == read_events(client, "events_json"), (
            "deletes_job succeeded and marked requests deleted, but the event tables differ"
        )
    assert {(row[0], row[1]) for row in after_events} == controls
    assert after_events == [row for row in before if (row[0], row[1]) in controls]
    for shard_index, client in enumerate(event_nodes):
        expected = {(row[0], row[1]) for row in rows[shard_index::2]} & controls
        assert survivors(client, EVENTS_JSON_DATA_TABLE) == expected
        assert client.execute("SELECT count() FROM system.dictionaries WHERE database = currentDatabase()") == [(0,)]
    verification = next(
        event
        for event in result.all_events
        if event.event_type_value == "STEP_OUTPUT" and event.step_key == "mark_deletions_verified"
    )
    counts = verification.step_output_data.metadata["unswept_rows"].value
    assert counts["events"] == 0
    assert counts["events_json"] is None
    assert counts[EVENTS_JSON_DATA_TABLE] == 0
