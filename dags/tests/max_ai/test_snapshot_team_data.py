import pytest
from unittest.mock import MagicMock, patch

import dagster
from dagster import OpExecutionContext
from dagster_aws.s3.resources import S3Resource

from posthog.schema import (
    ActorsPropertyTaxonomyResponse,
    CachedEventTaxonomyQueryResponse,
    CachedTeamTaxonomyQueryResponse,
    EventTaxonomyItem,
    TeamTaxonomyItem,
)

from posthog.models import GroupTypeMapping, Organization, Project, Team
from posthog.models.property_definition import PropertyDefinition

from products.enterprise.backend.hogai.eval.schema import PostgresTeamDataSnapshot, TeamSnapshot

from dags.max_ai.snapshot_team_data import (
    SnapshotUnrecoverableError,
    snapshot_actors_property_taxonomy,
    snapshot_clickhouse_team_data,
    snapshot_events_taxonomy,
    snapshot_postgres_model,
    snapshot_postgres_team_data,
    snapshot_properties_taxonomy,
)


@pytest.fixture
def mock_context():
    context = MagicMock(spec=OpExecutionContext)
    context.log = MagicMock()
    return context


@pytest.fixture
def mock_s3():
    mock = MagicMock(spec=S3Resource)
    mock.get_resource_definition = S3Resource().get_resource_definition
    return mock


@pytest.fixture
def team():
    organization = Organization.objects.create(name="Test")
    project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=organization)
    team = Team.objects.create(
        id=project.id,
        project=project,
        organization=organization,
        api_token="token123",
        test_account_filters=[
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ],
        has_completed_onboarding_for={"product_analytics": True},
    )
    yield team


@pytest.fixture
def mock_dump():
    with patch("dags.max_ai.snapshot_team_data.dump_model") as mock_dump_model:
        mock_dump_context = MagicMock()
        mock_dump_function = MagicMock()
        mock_dump_context.__enter__ = MagicMock(return_value=mock_dump_function)
        mock_dump_context.__exit__ = MagicMock(return_value=None)
        mock_dump_model.return_value = mock_dump_context
        yield mock_dump_function


@patch("dags.max_ai.snapshot_team_data.compose_postgres_dump_path")
@patch("dags.max_ai.snapshot_team_data.check_dump_exists")
def test_snapshot_postgres_model_skips_when_file_exists(
    mock_check_dump_exists, mock_compose_path, mock_context, mock_s3
):
    """Test that snapshot_postgres_model skips dumping when file already exists."""
    # Setup
    file_key = "test/path/teams_abc123.avro"
    mock_compose_path.return_value = file_key
    mock_check_dump_exists.return_value = True

    team_id = 123
    file_name = "teams"
    code_version = "v1"

    # Execute
    result = snapshot_postgres_model(
        context=mock_context,
        model_type=TeamSnapshot,
        file_name=file_name,
        s3=mock_s3,
        team_id=team_id,
        code_version=code_version,
    )

    # Verify
    assert result == file_key
    mock_compose_path.assert_called_once_with(team_id, file_name, code_version)
    mock_check_dump_exists.assert_called_once_with(mock_s3, file_key)
    mock_context.log.info.assert_called_once_with(f"Skipping {file_key} because it already exists")


@patch("dags.max_ai.snapshot_team_data.compose_postgres_dump_path")
@patch("dags.max_ai.snapshot_team_data.check_dump_exists")
def test_snapshot_postgres_model_dumps_when_file_not_exists(
    mock_check_dump_exists, mock_compose_path, mock_context, mock_s3, mock_dump
):
    """Test that snapshot_postgres_model dumps data when file doesn't exist."""
    # Setup
    file_key = "test/path/teams_abc123.avro"
    mock_compose_path.return_value = file_key
    mock_check_dump_exists.return_value = False

    # Mock the serialize_for_team method
    mock_serialized_data = [{"id": 1, "name": "test"}]
    with patch.object(TeamSnapshot, "serialize_for_team", return_value=mock_serialized_data):
        team_id = 123
        file_name = "teams"
        code_version = "v1"

        # Execute
        result = snapshot_postgres_model(
            context=mock_context,
            model_type=TeamSnapshot,
            file_name=file_name,
            s3=mock_s3,
            team_id=team_id,
            code_version=code_version,
        )

    # Verify
    assert result == file_key
    mock_compose_path.assert_called_once_with(team_id, file_name, code_version)
    mock_check_dump_exists.assert_called_once_with(mock_s3, file_key)
    mock_context.log.info.assert_called_with(f"Dumping {file_key}")
    mock_dump.assert_called_once_with(mock_serialized_data)


@patch("dags.max_ai.snapshot_team_data.snapshot_postgres_model")
def test_snapshot_postgres_team_data_exports_all_models(mock_snapshot_postgres_model, mock_s3):
    """Test that snapshot_postgres_team_data exports all expected models."""
    # Setup
    team_id = 456
    mock_snapshot_postgres_model.side_effect = [
        "path/to/team.avro",
        "path/to/property_definitions.avro",
        "path/to/group_type_mappings.avro",
        "path/to/data_warehouse_tables.avro",
    ]

    # Create context using Dagster's build_op_context
    context = dagster.build_op_context()

    # Execute
    result = snapshot_postgres_team_data(context, team_id, mock_s3)

    # Verify all expected models are in the result
    assert isinstance(result, PostgresTeamDataSnapshot)
    assert result.team == "path/to/team.avro"
    assert result.property_definitions == "path/to/property_definitions.avro"
    assert result.group_type_mappings == "path/to/group_type_mappings.avro"
    assert result.data_warehouse_tables == "path/to/data_warehouse_tables.avro"

    # Verify snapshot_postgres_model was called for each model type
    assert mock_snapshot_postgres_model.call_count == 4


@pytest.mark.django_db
@patch("dags.max_ai.snapshot_team_data.call_query_runner")
def test_snapshot_properties_taxonomy(mock_call_query_runner, mock_context, mock_s3, team, mock_dump):
    """Test that snapshot_properties_taxonomy correctly processes events and dumps results."""
    # Setup
    file_key = "test/path/properties_taxonomy.avro"
    events = [
        TeamTaxonomyItem(event="pageview", count=2),
        TeamTaxonomyItem(event="click", count=1),
    ]

    # Mock the query runner response
    mock_query_result = MagicMock()
    mock_query_result.results = [
        EventTaxonomyItem(property="$current_url", sample_values=["https://posthog.com"], sample_count=1),
    ]
    mock_call_query_runner.return_value = mock_query_result

    mock_s3_client = MagicMock()
    mock_s3.get_client.return_value = mock_s3_client

    snapshot_properties_taxonomy(mock_context, mock_s3, file_key, team, events)
    assert mock_call_query_runner.call_count == 2
    mock_dump.assert_called_once()


@patch("dags.max_ai.snapshot_team_data.snapshot_postgres_model")
def test_snapshot_postgres_team_data_raises_failure_on_missing_team(mock_snapshot_postgres_model, mock_s3):
    mock_snapshot_postgres_model.side_effect = Team.DoesNotExist()

    context = dagster.build_op_context()

    with pytest.raises(dagster.Failure) as exc:
        snapshot_postgres_team_data(context=context, team_id=999999, s3=mock_s3)

    assert getattr(exc.value, "allow_retries", None) is False
    assert "Team 999999 does not exist" in str(exc.value)


@pytest.mark.django_db
def test_snapshot_clickhouse_team_data_raises_failure_on_missing_team(mock_s3):
    context = dagster.build_op_context()

    with pytest.raises(dagster.Failure) as exc:
        snapshot_clickhouse_team_data(context=context, team_id=424242, s3=mock_s3)

    assert getattr(exc.value, "allow_retries", None) is False
    assert "Team 424242 does not exist" in str(exc.value)


@pytest.mark.django_db
@patch("dags.max_ai.snapshot_team_data.snapshot_events_taxonomy")
def test_snapshot_clickhouse_team_data_raises_failure_on_unrecoverable_error(
    mock_snapshot_events_taxonomy, mock_s3, team
):
    context = dagster.build_op_context()
    mock_snapshot_events_taxonomy.side_effect = SnapshotUnrecoverableError("boom")

    with pytest.raises(dagster.Failure) as exc:
        snapshot_clickhouse_team_data(context=context, team_id=team.id, s3=mock_s3)

    assert getattr(exc.value, "allow_retries", None) is False


@patch("dags.max_ai.snapshot_team_data.check_dump_exists")
@patch("dags.max_ai.snapshot_team_data.EventTaxonomyQueryRunner.run")
@patch("dags.max_ai.snapshot_team_data.TeamTaxonomyQueryRunner.run")
@pytest.mark.django_db
def test_snapshot_events_taxonomy(
    mock_team_taxonomy_query_runner,
    mock_event_taxonomy_query_runner,
    mock_check_dump_exists,
    mock_context,
    mock_s3,
    team,
    mock_dump,
):
    """Test that snapshot_events_taxonomy correctly processes events and dumps results."""
    mock_check_dump_exists.return_value = False

    mock_team_taxonomy_query_runner.return_value = MagicMock(
        spec=CachedTeamTaxonomyQueryResponse,
        results=[
            TeamTaxonomyItem(event="pageview", count=2),
            TeamTaxonomyItem(event="click", count=1),
        ],
    )

    mock_event_taxonomy_query_runner.return_value = MagicMock(
        spec=CachedEventTaxonomyQueryResponse,
        results=[
            EventTaxonomyItem(property="$current_url", sample_values=["https://posthog.com"], sample_count=1),
        ],
    )

    mock_s3_client = MagicMock()
    mock_s3.get_client.return_value = mock_s3_client

    snapshot_events_taxonomy(mock_context, mock_s3, team)
    mock_team_taxonomy_query_runner.assert_called_once()
    assert mock_event_taxonomy_query_runner.call_count == 2
    assert mock_dump.call_count == 2


@patch("dags.max_ai.snapshot_team_data.check_dump_exists")
@pytest.mark.django_db
def test_snapshot_events_taxonomy_can_be_skipped(mock_check_dump_exists, mock_context, mock_s3, team, mock_dump):
    """est that snapshot_events_taxonomy can be skipped when file already exists."""
    mock_check_dump_exists.return_value = True

    mock_s3_client = MagicMock()
    mock_s3.get_client.return_value = mock_s3_client

    snapshot_events_taxonomy(mock_context, mock_s3, team)
    assert mock_dump.call_count == 0


@patch("dags.max_ai.snapshot_team_data.check_dump_exists")
@pytest.mark.django_db
def test_snapshot_actors_property_taxonomy_can_be_skipped(
    mock_check_dump_exists, mock_context, mock_s3, team, mock_dump
):
    """Test that snapshot_actors_property_taxonomy can be skipped when file already exists."""
    mock_check_dump_exists.return_value = True

    mock_s3_client = MagicMock()
    mock_s3.get_client.return_value = mock_s3_client

    result = snapshot_actors_property_taxonomy(mock_context, mock_s3, team)

    # Should return file key even when skipped
    assert result is not None
    assert "actors_property_taxonomy" in result
    assert mock_dump.call_count == 0
    mock_context.log.info.assert_called_with(
        f"Skipping actors property taxonomy snapshot for {team.id} because it already exists"
    )


@patch("dags.max_ai.snapshot_team_data.check_dump_exists")
@patch("dags.max_ai.snapshot_team_data.call_query_runner")
@pytest.mark.django_db
def test_snapshot_actors_property_taxonomy_dumps_with_group_type_mapping(
    mock_call_query_runner, mock_check_dump_exists, mock_context, mock_s3, team, mock_dump
):
    """Test that snapshot_actors_property_taxonomy dumps data when GroupTypeMapping exists."""
    mock_check_dump_exists.return_value = False

    # Create a GroupTypeMapping for the team
    GroupTypeMapping.objects.create(
        team=team,
        project=team.project,
        group_type="organization",
        group_type_index=0,
        name_singular="Organization",
        name_plural="Organizations",
    )

    # Create PropertyDefinition objects for the group type
    PropertyDefinition.objects.create(
        team=team, name="org_name", type=PropertyDefinition.Type.GROUP, group_type_index=0
    )

    # Mock the query runner response
    mock_query_result = MagicMock()
    mock_query_result.results = [
        ActorsPropertyTaxonomyResponse(sample_values=["test_value_1", "test_value_2"], sample_count=2)
    ]
    mock_call_query_runner.return_value = mock_query_result

    mock_s3_client = MagicMock()
    mock_s3.get_client.return_value = mock_s3_client

    result = snapshot_actors_property_taxonomy(mock_context, mock_s3, team)

    # Should return file key
    assert result is not None
    assert "actors_property_taxonomy" in result

    # Should have called the query runner
    assert mock_call_query_runner.call_count > 0

    # Should have dumped data
    mock_dump.assert_called_once()
