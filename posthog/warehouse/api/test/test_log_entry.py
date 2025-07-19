import datetime as dt

import pytest
from django.test.client import Client as DjangoTestClient

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.clickhouse.client import sync_execute
from posthog.utils import encode_get_request_params
from posthog.warehouse.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
)


def create_external_data_job_log_entry(
    *,
    team_id: int,
    external_data_schema_id: str,
    run_id: str | None,
    message: str,
    level: str,
):
    from posthog.clickhouse.log_entries import INSERT_LOG_ENTRY_SQL

    sync_execute(
        INSERT_LOG_ENTRY_SQL,
        {
            "team_id": team_id,
            "log_source": "external_data_jobs",
            "log_source_id": external_data_schema_id,
            "instance_id": run_id,
            "timestamp": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "level": level,
            "message": message,
        },
    )


@pytest.fixture
def organization():
    organization = create_organization("Test Org")

    yield organization

    organization.delete()


@pytest.fixture
def team(organization):
    team = create_team(organization)

    yield team

    team.delete()


@pytest.fixture
def external_data_resources(client, organization, team):
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    source = ExternalDataSource.objects.create(
        team=team,
        source_id="source_id",
        connection_id="connection_id",
        status=ExternalDataSource.Status.COMPLETED,
        source_type=ExternalDataSource.Type.STRIPE,
    )
    credentials = DataWarehouseCredential.objects.create(access_key="blah", access_secret="blah", team=team)
    warehouse_table = DataWarehouseTable.objects.create(
        name="table_1",
        format="Parquet",
        team=team,
        external_data_source=source,
        external_data_source_id=source.id,
        credential=credentials,
        url_pattern="https://bucket.s3/data/*",
        columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
    )
    schema = ExternalDataSchema.objects.create(
        team=team,
        name="table_1",
        source=source,
        table=warehouse_table,
        should_sync=True,
        last_synced_at="2024-01-01",
        # No status but should be completed because a data warehouse table already exists
    )
    job = ExternalDataJob.objects.create(
        pipeline=source,
        schema=schema,
        workflow_id="fake_workflow_id",
        team=team,
        status="Running",
        rows_synced=100000,
        pipeline_version=ExternalDataJob.PipelineVersion.V1,
    )

    return {
        "source": source,
        "schema": schema,
        "job": job,
    }


def get_external_data_schema_run_log_entries(
    client: DjangoTestClient, team_id: int, external_data_schema_id: str, **extra
):
    return client.get(
        f"/api/environments/{team_id}/external_data_schemas/{external_data_schema_id}/logs",
        data=encode_get_request_params(extra),
    )


@pytest.mark.django_db
def test_external_data_schema_log_api_with_level_filter(client, external_data_resources, team):
    """Test fetching batch export run log entries using the API."""
    run_id = external_data_resources["job"].pk
    schema_id = external_data_resources["schema"].pk

    create_external_data_job_log_entry(
        team_id=team.pk,
        external_data_schema_id=schema_id,
        run_id=run_id,
        message="Test log. Much INFO.",
        level="INFO",
    )

    create_external_data_job_log_entry(
        team_id=team.pk,
        external_data_schema_id=schema_id,
        run_id="fake_workflow_id",
        message="Test log. Much INFO.",
        level="INFO",
    )

    create_external_data_job_log_entry(
        team_id=team.pk,
        external_data_schema_id=schema_id,
        run_id=run_id,
        message="Test log. Much DEBUG.",
        level="DEBUG",
    )

    response = get_external_data_schema_run_log_entries(
        client,
        team_id=team.pk,
        external_data_schema_id=schema_id,
        level="INFO",
        instance_id=run_id,
    )

    json_response = response.json()
    results = json_response["results"]

    assert response.status_code == 200
    assert json_response["count"] == 1
    assert len(results) == 1
    assert results[0]["message"] == "Test log. Much INFO."
    assert results[0]["level"] == "INFO"
    assert results[0]["log_source_id"] == str(schema_id)
