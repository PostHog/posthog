import asyncio

import pytest
import temporalio.client
from asgiref.sync import async_to_sync
from django.test.client import Client as HttpClient
from rest_framework import status
from temporalio.service import RPCError

from posthog.api.test.batch_exports.conftest import start_test_worker
from posthog.api.test.batch_exports.operations import (
    backfill_batch_export_ok,
    create_batch_export_ok,
    delete_batch_export,
    delete_batch_export_ok,
    get_batch_export,
)
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.batch_exports.service import describe_schedule
from posthog.temporal.client import sync_connect

pytestmark = [
    pytest.mark.django_db,
]


def test_delete_batch_export(client: HttpClient):
    """Test deleting a BatchExport."""
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
        batch_export = create_batch_export_ok(client, team.pk, batch_export_data)
        batch_export_id = batch_export["id"]

        delete_batch_export_ok(client, team.pk, batch_export_id)

        response = get_batch_export(client, team.pk, batch_export_id)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    with pytest.raises(RPCError):
        describe_schedule(temporal, batch_export_id)


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


@async_to_sync
async def wait_for_workflow_in_status(
    temporal: temporalio.client.Client,
    workflow_id: str,
    status: temporalio.client.WorkflowExecutionStatus,
    sleep: int = 1,
    timeout: int = 30,
):
    """Wait for a Workflow to be in a given status."""
    handle = temporal.get_workflow_handle(workflow_id)
    workflow = await handle.describe()

    total = 0
    while workflow.status != status:
        total += sleep

        if total > timeout:
            break

        await asyncio.sleep(sleep)
        workflow = await handle.describe()

    return workflow


@pytest.mark.django_db(transaction=True)
def test_delete_batch_export_cancels_backfills(client: HttpClient):
    """Test deleting a BatchExport cancels ongoing BatchExportBackfill."""
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
        batch_export = create_batch_export_ok(client, team.pk, batch_export_data)
        batch_export_id = batch_export["id"]

        start_at = "2023-10-23 00:00:00"
        end_at = "2023-10-24 00:00:00"
        batch_export_backfill = backfill_batch_export_ok(client, team.pk, batch_export_id, start_at, end_at)

        # In order for the backfill to be cancelable, it needs to be running and requesting backfills.
        # We check this by waiting for executions scheduled by our BatchExport id to pop up.
        _ = wait_for_workflow_executions(temporal, query=f'TemporalScheduledById="{batch_export_id}"')

        delete_batch_export_ok(client, team.pk, batch_export_id)

        response = get_batch_export(client, team.pk, batch_export_id)
        assert response.status_code == status.HTTP_404_NOT_FOUND

        workflow = wait_for_workflow_in_status(
            temporal,
            workflow_id=batch_export_backfill["backfill_id"],
            status=temporalio.client.WorkflowExecutionStatus.CANCELED,
        )
        assert workflow.status == temporalio.client.WorkflowExecutionStatus.CANCELED

    with pytest.raises(RPCError):
        describe_schedule(temporal, batch_export_id)


def test_cannot_delete_export_of_other_organizations(client: HttpClient):
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
    create_team(another_organization)
    another_user = create_user("another-test@user.com", "Another Test User", another_organization)

    with start_test_worker(temporal):
        client.force_login(user)
        batch_export = create_batch_export_ok(client, team.pk, batch_export_data)
        batch_export_id = batch_export["id"]

        client.force_login(another_user)
        response = delete_batch_export(client, team.pk, batch_export_id)
        assert response.status_code == status.HTTP_403_FORBIDDEN

        # Make sure we can still get the export with the right user
        client.force_login(user)
        response = get_batch_export(client, team.pk, batch_export_id)
        assert response.status_code == status.HTTP_200_OK


def test_deletes_are_partitioned_by_team_id(client: HttpClient):
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
        batch_export = create_batch_export_ok(client, team.pk, batch_export_data)
        batch_export_id = batch_export["id"]

        # Try to delete with the other team
        response = delete_batch_export(client, another_team.pk, batch_export_id)
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # Make sure we can still get the export with the right user
        response = get_batch_export(client, team.pk, batch_export_id)
        assert response.status_code == status.HTTP_200_OK
