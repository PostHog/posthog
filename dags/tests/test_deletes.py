import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from uuid import UUID

from dagster import build_op_context

from posthog.models.async_deletion import DeletionType
from posthog.clickhouse.cluster import Mutation, MutationRunner
from dags.deletes import (
    PendingPersonEventDeletesTable,
    load_pending_person_deletions,
    delete_person_events,
    cleanup_delete_assets,
)


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.execute.return_value = None  # Default return value for execute
    return client


@pytest.fixture
def mock_cluster():
    cluster = MagicMock()
    # Mock the client that any_host returns
    mock_client = MagicMock()
    mock_client.execute.return_value = None
    cluster.any_host.return_value.result.return_value = mock_client
    return cluster


def test_pending_person_deletes_table():
    table = PendingPersonEventDeletesTable(timestamp=datetime.now())
    assert table.table_name.startswith("pending_person_deletes_")

    create_query = table.create_table_query
    assert "CREATE TABLE IF NOT EXISTS" in create_query

    drop_query = table.drop_table_query
    assert "DROP TABLE IF EXISTS" in drop_query


def test_person_event_delete_mutation_runner():
    table = PendingPersonEventDeletesTable(timestamp=datetime.now())
    runner = table.person_event_delete_mutation_runner
    assert isinstance(runner, MutationRunner)

    # Test that the runner is configured for the events table
    assert runner.table == "sharded_events"


@patch("dags.deletes.Client")
@patch("dags.deletes.AsyncDeletion.objects")
def test_load_pending_person_deletions_with_team_id(mock_async_deletion, mock_client_class, mock_cluster):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    context = build_op_context()
    table = PendingPersonEventDeletesTable(team_id=1, timestamp=datetime.now())

    # Mock the queryset
    mock_deletions = [{"team_id": 1, "key": UUID("12345678-1234-5678-1234-567812345678"), "created_at": datetime.now()}]
    mock_async_deletion.filter.return_value.values.return_value.iterator.return_value = mock_deletions

    result = load_pending_person_deletions(context, table)
    assert isinstance(result, PendingPersonEventDeletesTable)
    mock_async_deletion.filter.assert_called_with(
        deletion_type=DeletionType.Person,
        team_id=1,
        delete_verified_at__isnull=True,
        created_at__lte=table.timestamp,
    )
    mock_client.execute.assert_called()


@patch("dags.deletes.Client")
@patch("dags.deletes.AsyncDeletion.objects")
def test_load_pending_person_deletions_without_team_id(mock_async_deletion, mock_client_class, mock_cluster):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    context = build_op_context()
    table = PendingPersonEventDeletesTable(timestamp=datetime.now())

    mock_deletions = [{"team_id": 1, "key": UUID("12345678-1234-5678-1234-567812345678"), "created_at": datetime.now()}]
    mock_async_deletion.filter.return_value.values.return_value.iterator.return_value = mock_deletions

    result = load_pending_person_deletions(context, table)
    assert isinstance(result, PendingPersonEventDeletesTable)
    mock_async_deletion.filter.assert_called_with(
        deletion_type=DeletionType.Person,
        delete_verified_at__isnull=True,
        created_at__lte=pytest.approx(table.timestamp, abs=1),
    )
    mock_client.execute.assert_called()


def test_delete_person_events_no_pending_deletes(mock_cluster):
    context = build_op_context()
    table = PendingPersonEventDeletesTable(timestamp=datetime.now())

    # Mock no pending deletes - return 0 for the count query
    mock_client = MagicMock()
    mock_client.execute.return_value = [[0]]
    mock_cluster.any_host.return_value.result.return_value = mock_client.execute.return_value[0][
        0
    ]  # Should match the execute result
    mock_cluster.map_all_hosts.return_value.result.return_value = None

    result = delete_person_events(context, mock_cluster, table)
    assert isinstance(result, tuple)
    assert result[1] == {}  # No mutations when no pending deletes


def test_delete_person_events_with_pending_deletes(mock_cluster):
    context = build_op_context()
    table = PendingPersonEventDeletesTable(timestamp=datetime.now())

    # Mock having pending deletes
    mock_client = MagicMock()
    mock_client.execute.return_value = [[5]]  # 5 pending deletes
    mock_cluster.any_host.return_value.result.return_value = mock_client.execute.return_value[0][
        0
    ]  # Should match the execute result

    # Mock the mutation result
    mock_mutation = MagicMock(spec=Mutation)
    mock_host = MagicMock()
    mock_host.shard_num = 1
    mock_cluster.map_one_host_per_shard.return_value.result.return_value = {mock_host: mock_mutation}

    # Patch the MutationRunner class before creating an instance
    with patch("posthog.clickhouse.cluster.MutationRunner.enqueue", return_value=mock_mutation) as mock_enqueue:
        result = delete_person_events(context, mock_cluster, table)

        # Verify the mutation runner's enqueue method was called
        mock_cluster.map_one_host_per_shard.assert_called_once()
        actual_enqueue = mock_cluster.map_one_host_per_shard.call_args[0][0]
        assert actual_enqueue == mock_enqueue

        assert isinstance(result, tuple)
        assert isinstance(result[1], dict)
        assert len(result[1]) == 1
        assert 1 in result[1]  # Should have mutation for shard 1
        assert result[1][1] == mock_mutation


def test_cleanup_delete_assets(mock_cluster):
    table = PendingPersonEventDeletesTable(timestamp=datetime.now())

    with patch("dags.deletes.AsyncDeletion.objects") as mock_async_deletion:
        result = cleanup_delete_assets(mock_cluster, table, table)
        assert result is True
        mock_async_deletion.filter.assert_called_with(
            deletion_type=DeletionType.Person,
            delete_verified_at__isnull=True,
            created_at__lte=pytest.approx(table.timestamp, abs=1),
        )
