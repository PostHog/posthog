import json
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from posthog.temporal.tests.data_imports.conftest import run_external_data_job_workflow
from posthog.temporal.tests.data_imports.github.data import COMMITS, ISSUES, PULL_REQUESTS, WORKFLOW_JOBS, WORKFLOW_RUNS

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

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
            "auth_method": {"selection": "pat", "personal_access_token": "test-token"},
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


@pytest.fixture
def external_data_schema_workflow_runs_full_refresh(external_data_source, team):
    return ExternalDataSchema.objects.create(
        name="workflow_runs",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="full_refresh",
        sync_type_config={},
    )


@pytest.fixture
def external_data_schema_workflow_runs_incremental(external_data_source, team):
    return ExternalDataSchema.objects.create(
        name="workflow_runs",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="incremental",
        sync_type_config={"incremental_field": "created_at", "incremental_field_type": "datetime"},
    )


@pytest.fixture
def external_data_schema_workflow_jobs_full_refresh(external_data_source, team):
    return ExternalDataSchema.objects.create(
        name="workflow_jobs",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="full_refresh",
        sync_type_config={},
    )


@mock.patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
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


@mock.patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
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


@mock.patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
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


@mock.patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
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


@mock.patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_github_workflow_runs_full_refresh(
    team, mock_github_api, external_data_source, external_data_schema_workflow_runs_full_refresh
):
    expected_num_rows = len(WORKFLOW_RUNS)

    await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_workflow_runs_full_refresh,
        table_name="github_workflow_runs",
        expected_rows_synced=expected_num_rows,
        expected_total_rows=expected_num_rows,
    )

    api_calls = mock_github_api.get_all_api_calls()
    assert len(api_calls) == 1
    assert "/repos/owner/repo/actions/runs" in api_calls[0].url
    # workflow_runs is a minimal-params endpoint: no sort/direction/state.
    first_call_params = parse_qs(urlparse(api_calls[0].url).query)
    assert "sort" not in first_call_params
    assert "direction" not in first_call_params
    assert "state" not in first_call_params
    assert "created" not in first_call_params


@mock.patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_github_workflow_runs_incremental(
    team, mock_github_api, external_data_source, external_data_schema_workflow_runs_incremental
):
    # Single-sync test mirroring the pull_requests/commits incremental tests:
    # workflow_runs scrolls newest-first and bounds incremental syncs via
    # client-side early-stop (no server filter), so the request shape is what
    # matters here. The newest-first re-read + primary-key dedup across syncs is
    # the pipeline merge's job; exercising it through two rapid in-harness syncs
    # is flaky, so the desc early-stop overlap is covered deterministically in
    # test_github_source.py instead.
    expected_num_rows = len(WORKFLOW_RUNS)

    await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_workflow_runs_incremental,
        table_name="github_workflow_runs",
        expected_rows_synced=expected_num_rows,
        expected_total_rows=expected_num_rows,
    )

    api_calls = mock_github_api.get_all_api_calls()
    assert len(api_calls) == 1
    assert "/repos/owner/repo/actions/runs" in api_calls[0].url
    # No created/since/sort/state — the 1,000-result search cap is only hit when
    # those filters are sent, so workflow_runs avoids them entirely.
    first_call_params = parse_qs(urlparse(api_calls[0].url).query)
    assert "created" not in first_call_params
    assert "since" not in first_call_params
    assert "sort" not in first_call_params
    assert "direction" not in first_call_params
    assert "state" not in first_call_params


@mock.patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_github_workflow_jobs_full_refresh(
    team, mock_github_api, external_data_source, external_data_schema_workflow_jobs_full_refresh
):
    # workflow_jobs fans out over workflow_runs: one parent runs request, then one
    # jobs request per run. Single sync only — cross-sync merge is the pipeline's
    # job and is flaky to exercise in-harness, so the desc early-stop overlap is
    # covered deterministically in test_github_source.py instead.
    expected_num_rows = len(WORKFLOW_JOBS)

    await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_workflow_jobs_full_refresh,
        table_name="github_workflow_jobs",
        expected_rows_synced=expected_num_rows,
        expected_total_rows=expected_num_rows,
    )

    api_calls = mock_github_api.get_all_api_calls()
    # 1 parent runs page + 1 jobs request per run (3 runs).
    assert len(api_calls) == 1 + len({job["run_id"] for job in WORKFLOW_JOBS})
    parent_calls = [c for c in api_calls if c.url.rstrip("/").endswith("/actions/runs") or "/actions/runs?" in c.url]
    jobs_calls = [c for c in api_calls if "/jobs" in c.url]
    assert len(parent_calls) == 1
    assert len(jobs_calls) == 3
    # Every job request carries filter=all (jobs across all run_attempts) and no
    # search-cap-tripping filters.
    for call in jobs_calls:
        params = parse_qs(urlparse(call.url).query)
        assert params["filter"] == ["all"]
        assert "created" not in params
        assert "since" not in params


@mock.patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_github_workflow_jobs_load_bearing_fields_land_queryable(
    team, mock_github_api, external_data_source, external_data_schema_workflow_jobs_full_refresh
):
    # Every column the engineering_analytics cost model reads must survive the
    # fan-out and stay queryable. This is the full WORKFLOW_JOBS_COLUMNS contract
    # (products/engineering_analytics/.../views/source_schema.py); a column dropped
    # here breaks per-PR attribution (run_id/head_branch), retry analysis
    # (run_attempt), duration/cost (started_at/completed_at), or runner-tier parsing
    # (labels). Nested steps/labels must arrive as JSON lists, not flattened.
    expected_num_rows = len(WORKFLOW_JOBS)
    load_bearing_columns = [
        "id",
        "run_id",
        "run_attempt",
        "name",
        "workflow_name",
        "status",
        "conclusion",
        "head_sha",
        "head_branch",
        "labels",
        "runner_name",
        "runner_group_name",
        "created_at",
        "started_at",
        "completed_at",
        "steps",
    ]

    res = await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_workflow_jobs_full_refresh,
        table_name="github_workflow_jobs",
        expected_rows_synced=expected_num_rows,
        expected_total_rows=expected_num_rows,
        expected_columns=load_bearing_columns,
    )

    columns = res.columns
    assert columns is not None
    col_idx = {name: i for i, name in enumerate(columns)}
    rows_by_id = {row[col_idx["id"]]: row for row in res.results}
    # Job 20001 carries the full field set, including labels + runner_group_name.
    job = rows_by_id[20001]

    def value(column: str):
        return job[col_idx[column]]

    assert value("run_id") == 1001
    assert value("run_attempt") == 1
    assert value("name") == "build"
    assert value("workflow_name") == "CI"
    assert value("status") == "completed"
    assert value("conclusion") == "success"
    assert value("head_sha") == "abc123"
    assert value("head_branch") == "master"
    assert value("runner_name") == "ubuntu-latest"
    assert value("runner_group_name") == "GitHub Actions"
    # Timestamps land as strings (parsed reader-side); duration = completed - started.
    assert value("started_at") == "2026-01-20T10:00:30Z"
    assert value("completed_at") == "2026-01-20T10:10:00Z"

    # steps + labels are stored as JSON; they must round-trip as lists, not
    # stringified scalars or dropped columns.
    steps = json.loads(value("steps")) if isinstance(value("steps"), str) else value("steps")
    labels = json.loads(value("labels")) if isinstance(value("labels"), str) else value("labels")
    assert isinstance(steps, list) and len(steps) == 2
    assert labels == ["depot-ubuntu-latest-4"]
