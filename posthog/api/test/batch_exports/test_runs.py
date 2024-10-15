import asyncio

import pytest
import temporalio.client
from asgiref.sync import async_to_sync
from django.test.client import Client as HttpClient
from rest_framework import status

from posthog.api.test.batch_exports.conftest import start_test_worker
from posthog.api.test.batch_exports.operations import (
    backfill_batch_export_ok,
    cancel_batch_export_run_ok,
    create_batch_export_ok,
    get_batch_export,
    get_batch_export_runs,
    get_batch_export_runs_ok,
)
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.temporal.common.client import sync_connect

pytestmark = [
    pytest.mark.django_db,
]


def test_can_get_export_runs_for_your_organizations(client: HttpClient):
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

        response = get_batch_export_runs(client, team.pk, response["id"])
        assert response.status_code == status.HTTP_200_OK, response.json()


def test_cannot_get_exports_for_other_organizations(client: HttpClient):
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
    }

    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)

    another_organization = create_organization("Another Org")
    another_user = create_user("another-test@user.com", "Another Test User", another_organization)

    with start_test_worker(temporal):
        client.force_login(user)
        response = create_batch_export_ok(
            client,
            team.pk,
            batch_export_data,
        )

        client.force_login(another_user)
        response = get_batch_export_runs(client, team.pk, response["id"])
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()


def test_batch_exports_are_partitioned_by_team(client: HttpClient):
    """
    You shouldn't be able to fetch a BatchExport by id, via a team that it
    doesn't belong to.
    """
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
    }

    organization = create_organization("Test Org")
    team = create_team(organization)
    another_team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)

    with start_test_worker(temporal):
        client.force_login(user)
        batch_export = create_batch_export_ok(
            client,
            team.pk,
            batch_export_data,
        )

        response = get_batch_export(client, another_team.pk, batch_export["id"])
        assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()

        # And switch the teams around for good measure.
        batch_export = create_batch_export_ok(
            client,
            another_team.pk,
            batch_export_data,
        )

        response = get_batch_export(client, team.pk, batch_export["id"])
        assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()


# TODO - this was in test_delete.py too so maybe extract it out into operations.py?
@async_to_sync
async def wait_for_workflow_executions(
    temporal: temporalio.client.Client, query: str, timeout: int = 30, sleep: int = 1
):
    """Wait for Workflow Executions matching query."""
    workflows = [workflow async for workflow in temporal.list_workflows(query=query)]

    total = 0
    while not workflows:
        total += sleep

        if total > timeout:
            raise TimeoutError(f"No backfill Workflow Executions after {timeout} seconds")

        await asyncio.sleep(sleep)
        workflows = [workflow async for workflow in temporal.list_workflows(query=query)]

    return workflows


@pytest.mark.django_db(transaction=True)
def test_cancelling_a_batch_export_run(client: HttpClient):
    """Test cancelling a BatchExportRun."""
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
    }

    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    with start_test_worker(temporal):
        batch_export = create_batch_export_ok(
            client,
            team.pk,
            batch_export_data,
        )
        batch_export_id = batch_export["id"]

        start_at = "2023-10-23T00:00:00+00:00"
        end_at = "2023-10-24T00:00:00+00:00"
        backfill_batch_export_ok(client, team.pk, batch_export_id, start_at, end_at)

        # In order for a run to be cancelable we need a running workflow execution
        _ = wait_for_workflow_executions(temporal, query=f'TemporalScheduledById="{batch_export_id}"')

        data = get_batch_export_runs_ok(client, team.pk, batch_export_id)
        assert len(data["results"]) == 1
        run = data["results"][0]
        assert run["status"] == "Running"

        data = cancel_batch_export_run_ok(client, team.pk, batch_export_id, run["id"])
        assert data["cancelled"] is True

        data = get_batch_export_runs_ok(client, team.pk, batch_export_id)
        assert len(data["results"]) == 1
        run = data["results"][0]
        assert run["status"] == "Cancelled"


# TODO - add a test to ensure we can't cancel a completed run?
