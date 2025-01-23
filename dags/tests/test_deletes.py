import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from uuid import UUID

from dagster import build_op_context

from posthog.models.async_deletion import DeletionType
from dags.deletes import (
    PendingPersonEventDeletesTable,
    PersonEventDeletesDictionary,
    Mutation,
    load_pending_person_deletions,
    create_pending_deletes_dictionary,
    delete_person_events,
    cleanup_delete_assets,
    DeleteConfig,
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
    table = PendingPersonEventDeletesTable(run_id="test_run")
    assert table.table_name == "pending_person_deletes_test_run"

    create_query = table.create_table_query
    assert "CREATE TABLE IF NOT EXISTS" in create_query

    drop_query = table.drop_table_query()
    assert "DROP TABLE IF EXISTS" in drop_query


def test_mutation_is_done(mock_client):
    mutation = Mutation(table="test_table", mutation_id="test_mutation")
    mock_client.execute.return_value = [[True]]
    assert mutation.is_done(mock_client) is True

    mock_client.execute.return_value = [[False]]
    assert mutation.is_done(mock_client) is False

    mock_client.execute.return_value = []
    assert mutation.is_done(mock_client) is False


def test_person_event_deletes_dictionary():
    table = PendingPersonEventDeletesTable(run_id="test_run")
    dictionary = PersonEventDeletesDictionary(source=table)

    assert dictionary.name == "pending_person_deletes_test_run_dict"
    assert "CREATE DICTIONARY IF NOT EXISTS" in dictionary.create_statement(shards=1, max_execution_time=3600)


@patch("dags.deletes.Client")
@patch("dags.deletes.AsyncDeletion.objects")
def test_load_pending_person_deletions_with_team_id(mock_async_deletion, mock_client_class, mock_cluster):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    context = build_op_context()
    config = DeleteConfig(team_id=1)
    table = PendingPersonEventDeletesTable(run_id=context.run_id)

    # Mock the queryset
    mock_deletions = [{"team_id": 1, "key": UUID("12345678-1234-5678-1234-567812345678"), "created_at": datetime.now()}]
    mock_async_deletion.filter.return_value.values.return_value.iterator.return_value = mock_deletions

    result = load_pending_person_deletions(context, config, table)
    assert isinstance(result, PendingPersonEventDeletesTable)
    mock_async_deletion.filter.assert_called_with(
        deletion_type=DeletionType.Person,
        team_id=1,
        delete_verified_at__isnull=True,
    )
    mock_client.execute.assert_called()


@patch("dags.deletes.Client")
@patch("dags.deletes.AsyncDeletion.objects")
def test_load_pending_person_deletions_without_team_id(mock_async_deletion, mock_client_class, mock_cluster):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    context = build_op_context()
    config = DeleteConfig(team_id=None)
    table = PendingPersonEventDeletesTable(run_id=context.run_id)

    mock_deletions = [{"team_id": 1, "key": UUID("12345678-1234-5678-1234-567812345678"), "created_at": datetime.now()}]
    mock_async_deletion.filter.return_value.values.return_value.iterator.return_value = mock_deletions

    result = load_pending_person_deletions(context, config, table)
    assert isinstance(result, PendingPersonEventDeletesTable)
    mock_async_deletion.filter.assert_called_with(
        deletion_type=DeletionType.Person,
        delete_verified_at__isnull=True,
    )
    mock_client.execute.assert_called()


def test_create_pending_deletes_dictionary(mock_cluster):
    context = build_op_context()
    table = PendingPersonEventDeletesTable(run_id=context.run_id)

    result = create_pending_deletes_dictionary(mock_cluster, table)
    assert isinstance(result, PersonEventDeletesDictionary)
    mock_cluster.any_host.assert_called()


def test_delete_person_events_no_pending_deletes(mock_cluster):
    context = build_op_context()
    dictionary = PersonEventDeletesDictionary(source=PendingPersonEventDeletesTable(run_id="test_run"))

    # Mock no pending deletes
    mock_cluster.any_host.return_value.result.return_value = 0

    result = delete_person_events(context, mock_cluster, dictionary)
    assert isinstance(result, tuple)
    assert result[1] == {}  # No mutations when no pending deletes


def test_cleanup_delete_assets(mock_cluster):
    context = build_op_context()
    config = DeleteConfig(team_id=1)
    table = PendingPersonEventDeletesTable(run_id=context.run_id)
    dictionary = PersonEventDeletesDictionary(source=table)

    with patch("dags.deletes.AsyncDeletion.objects") as mock_async_deletion:
        result = cleanup_delete_assets(mock_cluster, config, table, dictionary)
        assert result is True
        mock_async_deletion.filter.assert_called_with(
            deletion_type=DeletionType.Person,
            team_id=1,
            delete_verified_at__isnull=True,
        )
