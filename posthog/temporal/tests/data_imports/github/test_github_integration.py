import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from posthog.temporal.tests.data_imports.conftest import run_external_data_job_workflow
from posthog.temporal.tests.data_imports.github.data import COMMITS, ISSUES, PULL_REQUESTS

from products.data_warehouse.backend.models import ExternalDataSchema, ExternalDataSource

pytestmark = pytest.mark.usefixtures("minio_client")


@pytest.fixture
def external_data_source(team):
    return ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="Github",
        job_inputs={
            "auth_type": {"selection": "pat", "personal_access_token": "test-token"},
            "repository": "owner/repo",
        },
    )


@pytest.fixture
def external_data_schema_issues_full_refresh(external_data_source, team):
    return ExternalDataSchema.objects.create(
        name="issues",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="full_refresh",
        sync_type_config={},
    )


@pytest.fixture
def external_data_schema_issues_incremental(external_data_source, team):
    return ExternalDataSchema.objects.create(
        name="issues",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="incremental",
        sync_type_config={"incremental_field": "updated_at", "incremental_field_type": "datetime"},
    )


@pytest.fixture
def external_data_schema_commits_incremental(external_data_source, team):
    return ExternalDataSchema.objects.create(
        name="commits",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="incremental",
        sync_type_config={"incremental_field": "created_at", "incremental_field_type": "datetime"},
    )


@pytest.fixture
def external_data_schema_pull_requests_incremental(external_data_source, team):
    return ExternalDataSchema.objects.create(
        name="pull_requests",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="incremental",
        sync_type_config={"incremental_field": "updated_at", "incremental_field_type": "datetime"},
    )


@mock.patch("posthog.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_github_issues_full_refresh(
    team, mock_github_api, external_data_source, external_data_schema_issues_full_refresh
):
    # Issues endpoint filters out PRs - items 1, 2, 4, 5 are real issues, item 3 is a PR
    expected_num_rows = len([i for i in ISSUES if "pull_request" not in i or i["pull_request"] is None])

    await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_issues_full_refresh,
        table_name="github_issues",
        expected_rows_synced=expected_num_rows,
        expected_total_rows=expected_num_rows,
    )

    api_calls = mock_github_api.get_all_api_calls()
    assert len(api_calls) == 1
    assert "/repos/owner/repo/issues" in api_calls[0].url


@mock.patch("posthog.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_github_issues_incremental(
    team, mock_github_api, external_data_source, external_data_schema_issues_incremental
):
    # First sync: limit data to items updated on or before Jan 20
    mock_github_api.set_max_updated("2026-01-20T10:00:00Z")

    # Only items 1 and 5 have updated_at <= Jan 20, and neither is a PR
    expected_rows_synced = 2
    expected_total_rows = 2

    await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_issues_incremental,
        table_name="github_issues",
        expected_rows_synced=expected_rows_synced,
        expected_total_rows=expected_total_rows,
    )

    api_calls = mock_github_api.get_all_api_calls()
    assert len(api_calls) == 1
    # First sync uses created asc default for stable pagination
    first_call_params = parse_qs(urlparse(api_calls[0].url).query)
    assert "since" not in first_call_params
    assert first_call_params.get("sort") == ["created"]
    assert first_call_params.get("direction") == ["asc"]

    # Second sync: make all data visible
    mock_github_api.reset_max_updated()

    # Items with updated_at > Jan 20 that are not PRs: items 2 (Jan 22), 4 (Jan 25)
    # Plus item 3 is a PR so filtered out, so 2 new items
    # Total should be 4 (2 from before + 2 new)
    expected_rows_synced = 2
    expected_total_rows = 4

    await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_issues_incremental,
        table_name="github_issues",
        expected_rows_synced=expected_rows_synced,
        expected_total_rows=expected_total_rows,
    )

    api_calls = mock_github_api.get_all_api_calls()
    assert len(api_calls) == 2
    # Second sync should use since param
    second_call_params = parse_qs(urlparse(api_calls[1].url).query)
    assert "since" in second_call_params


@mock.patch("posthog.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_github_commits_incremental(
    team, mock_github_api, external_data_source, external_data_schema_commits_incremental
):
    expected_num_rows = len(COMMITS)

    await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_commits_incremental,
        table_name="github_commits",
        expected_rows_synced=expected_num_rows,
        expected_total_rows=expected_num_rows,
    )

    api_calls = mock_github_api.get_all_api_calls()
    assert len(api_calls) == 1
    assert "/repos/owner/repo/commits" in api_calls[0].url


@mock.patch("posthog.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_github_pull_requests_incremental(
    team, mock_github_api, external_data_source, external_data_schema_pull_requests_incremental
):
    expected_num_rows = len(PULL_REQUESTS)

    await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_pull_requests_incremental,
        table_name="github_pull_requests",
        expected_rows_synced=expected_num_rows,
        expected_total_rows=expected_num_rows,
    )

    api_calls = mock_github_api.get_all_api_calls()
    assert len(api_calls) == 1
    first_call_params = parse_qs(urlparse(api_calls[0].url).query)
    # First sync uses created asc for stable offset-based pagination
    assert first_call_params.get("sort") == ["created"]
    assert first_call_params.get("direction") == ["asc"]
    assert "since" not in first_call_params
