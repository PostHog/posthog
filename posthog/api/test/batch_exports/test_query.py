import pytest
from django.test.client import Client as HttpClient

from posthog.api.test.batch_exports.conftest import start_test_worker
from posthog.api.test.batch_exports.fixtures import create_organization
from posthog.api.test.batch_exports.operations import (
    create_batch_export_ok,
    new_query_batch_export_ok,
    query_batch_export_ok,
)
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.temporal.common.client import sync_connect

pytestmark = [
    pytest.mark.django_db,
]


@pytest.mark.parametrize(
    "query",
    [
        "SELECT event FROM events",
    ],
)
def test_query_returns_existing_batch_export_query(client: HttpClient, query):
    """Test query endpoint returns a BatchExport's query."""
    temporal = sync_connect()

    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
        "hogql_query": query,
    }

    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    with start_test_worker(temporal):
        response = create_batch_export_ok(
            client,
            team.pk,
            batch_export_data,
        )
        batch_export_id = response["id"]

        response = query_batch_export_ok(client, team.pk, batch_export_id)

        assert response["kind"] == "HogQLQuery"
        assert response["query"] == query


@pytest.mark.parametrize(
    "destination_type",
    [
        "S3",
        "Redshift",
        "Postgres",
        "BigQuery",
        "Snowflake",
        "HTTP",
    ],
)
@pytest.mark.parametrize(
    "model",
    [
        "events",
        "persons",
    ],
)
def test_query_returns_default_batch_export_query_for_new_batch_export(client: HttpClient, destination_type, model):
    """Test query endpoint returns a BatchExport's default query for a new batch export."""
    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    response = new_query_batch_export_ok(client, team.pk, destination_type, model)
    query_file = f"events_{destination_type.lower()}.sql" if model == "events" else "persons.sql"

    with open(f"posthog/batch_exports/sql/{query_file}") as f:
        query = f.read()

    assert response["kind"] == "HogQLQuery"
    assert response["query"] == query
