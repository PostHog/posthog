import asyncio
import datetime as dt

import pytest
from posthog.test.base import _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.models.integration import Integration

from products.batch_exports.backend.models.batch_export import BatchExportRun
from products.batch_exports.backend.tests.api.fixtures import (
    create_batch_export,
    create_destination,
    create_organization,
    create_run,
    create_team,
    create_user,
)
from products.batch_exports.backend.tests.api.operations import (
    backfill_batch_export_ok,
    cancel_batch_export_run,
    cancel_batch_export_run_ok,
    create_batch_export_ok,
    get_batch_export,
    get_batch_export_runs,
    get_batch_export_runs_ok,
    wait_for_workflow_executions,
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


def test_can_get_export_runs_for_your_organizations(
    client: HttpClient, temporal, organization, team, user, aws_s3_integration
):
    destination_data = {
        "type": "AwsS3",
        "integration": aws_s3_integration.id,
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

    client.force_login(user)
    response = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    response = get_batch_export_runs(client, team.pk, response["id"])
    assert response.status_code == status.HTTP_200_OK, response.json()


def test_cannot_get_exports_for_other_organizations(
    client: HttpClient, temporal, organization, team, user, aws_s3_integration
):
    destination_data = {
        "type": "AwsS3",
        "integration": aws_s3_integration.id,
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

    another_organization = create_organization("Another Org")
    another_user = create_user("another-test@user.com", "Another Test User", another_organization)
    client.force_login(user)
    response = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    client.force_login(another_user)
    response = get_batch_export_runs(client, team.pk, response["id"])
    assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()


def test_batch_exports_are_partitioned_by_team(
    client: HttpClient, temporal, organization, team, user, aws_s3_integration
):
    """
    You shouldn't be able to fetch a BatchExport by id, via a team that it
    doesn't belong to.
    """
    destination_data = {
        "type": "AwsS3",
        "integration": aws_s3_integration.id,
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

    another_team = create_team(organization)
    # Integrations are team-scoped, so the other team's export needs its own.
    another_team_integration = Integration.objects.create(
        team=another_team,
        kind=Integration.IntegrationKind.AWS_S3,
        integration_id="prod-aws",
        config={"name": "prod-aws", "aws_account_id": "123456789012"},
        sensitive_config={"aws_access_key_id": "key", "aws_secret_access_key": "secret"},
        created_by=user,
    )
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
        {**batch_export_data, "destination": {**destination_data, "integration": another_team_integration.id}},
    )

    response = get_batch_export(client, team.pk, batch_export["id"])
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()


@pytest.mark.django_db(transaction=True)
def test_cancelling_a_batch_export_run(client: HttpClient, temporal, organization, team, user, aws_s3_integration):
    """Test cancelling a BatchExportRun."""
    destination_data = {
        "type": "AwsS3",
        "integration": aws_s3_integration.id,
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

    client.force_login(user)

    with patch("products.batch_exports.backend.temporal.pipeline.producer.Producer.start") as mock_producer_start:
        # Mock the producer to sleep so we can test cancellation
        async def mock_sleep(*args, **kwargs):
            await asyncio.sleep(30)
            return None

        mock_producer_start.side_effect = mock_sleep

        batch_export = create_batch_export_ok(
            client,
            team.pk,
            batch_export_data,
        )
        batch_export_id = batch_export["id"]

        # ensure there is data to backfill, otherwise validation will fail
        _create_event(
            team=team,
            event="$pageview",
            distinct_id="person_1",
            timestamp=dt.datetime(2023, 10, 23, 0, 1, 0, tzinfo=dt.UTC),
        )
        flush_persons_and_events()

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


@pytest.mark.parametrize("ordering", [None, "-data_interval_start"])
def test_get_batch_export_runs_filtered_by_status(client: HttpClient, team, user, ordering):
    batch_export = create_batch_export(team, create_destination())
    # Runs are only returned when their data interval falls inside the default window of the last 7 days.
    interval_end = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    runs = {}
    for hours, run_status in enumerate(
        [
            BatchExportRun.Status.COMPLETED,
            BatchExportRun.Status.FAILED,
            BatchExportRun.Status.FAILED_RETRYABLE,
            BatchExportRun.Status.RUNNING,
        ]
    ):
        runs[run_status] = create_run(
            batch_export,
            status=run_status,
            data_interval_start=interval_end - dt.timedelta(hours=hours + 1),
            data_interval_end=interval_end - dt.timedelta(hours=hours),
        )

    client.force_login(user)
    query_params = {"ordering": ordering} if ordering else {}

    # List runs filtered by failed statuses, asserting that only failed runs are returned
    data = get_batch_export_runs_ok(
        client,
        team.pk,
        batch_export.id,
        status=[BatchExportRun.Status.FAILED, BatchExportRun.Status.FAILED_RETRYABLE],
        **query_params,
    )
    assert {run["id"] for run in data["results"]} == {
        str(runs[BatchExportRun.Status.FAILED].id),
        str(runs[BatchExportRun.Status.FAILED_RETRYABLE].id),
    }

    # List all runs, without any status filter, asserting that all runs are returned
    data = get_batch_export_runs_ok(client, team.pk, batch_export.id, **query_params)
    assert {run["id"] for run in data["results"]} == {str(run.id) for run in runs.values()}


def test_get_batch_export_runs_rejects_unknown_status(client: HttpClient, team, user):
    batch_export = create_batch_export(team, create_destination())
    client.force_login(user)

    response = get_batch_export_runs(client, team.pk, batch_export.id, status=["NotAStatus"])

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()


def test_get_batch_export_runs_date_filter_depends_on_ordering(client: HttpClient, team, user):
    batch_export = create_batch_export(team, create_destination())
    now = dt.datetime.now(dt.UTC)

    def days_ago(days: float) -> dt.datetime:
        return now - dt.timedelta(days=days)

    # Backfilled today for a 40-day-old interval
    run_old_interval = create_run(
        batch_export,
        status=BatchExportRun.Status.COMPLETED,
        data_interval_start=days_ago(40) - dt.timedelta(hours=1),
        data_interval_end=days_ago(40),
    )

    # Backfilled 10 days ago for a 20-day-old interval.
    run_mid_interval = create_run(
        batch_export,
        status=BatchExportRun.Status.COMPLETED,
        data_interval_start=days_ago(20) - dt.timedelta(hours=1),
        data_interval_end=days_ago(20),
    )
    BatchExportRun.objects.filter(id=run_mid_interval.id).update(created_at=days_ago(10))

    # A normal, on-schedule run: created right as its 5-day-old interval ended.
    run_recent_interval = create_run(
        batch_export,
        status=BatchExportRun.Status.COMPLETED,
        data_interval_start=days_ago(5) - dt.timedelta(hours=1),
        data_interval_end=days_ago(5),
    )
    BatchExportRun.objects.filter(id=run_recent_interval.id).update(created_at=days_ago(5))

    client.force_login(user)

    # Default ordering sorts and filters by created_at: today (run_old_interval), then 5 days ago
    # (run_recent_interval); 10 days ago (run_mid_interval) falls outside the 8-day window.
    # `start` is passed too and must have no effect: applied, it would exclude run_old_interval's
    # 40-day-old interval.
    data = get_batch_export_runs_ok(client, team.pk, batch_export.id, after="-8d", start="-25d")
    assert [run["id"] for run in data["results"]] == [str(run_old_interval.id), str(run_recent_interval.id)]

    # Ordering by data_interval_start instead sorts and filters by the interval: 5 days ago
    # (run_recent_interval), then 20 days ago (run_mid_interval); 40 days ago (run_old_interval)
    # falls outside the 25-day window. `before` is passed too and must have no effect: applied, it
    # would exclude run_recent_interval, which was created only 5 days ago.
    data = get_batch_export_runs_ok(
        client, team.pk, batch_export.id, ordering="-data_interval_start", start="-25d", before="-8d"
    )
    assert [run["id"] for run in data["results"]] == [str(run_recent_interval.id), str(run_mid_interval.id)]


def test_cannot_cancel_completed_batch_export_run(client: HttpClient, team, user):
    destination = create_destination()
    batch_export = create_batch_export(team, destination)
    run = create_run(
        batch_export,
        status=BatchExportRun.Status.COMPLETED,
        data_interval_start=dt.datetime(2023, 10, 23, tzinfo=dt.UTC),
        data_interval_end=dt.datetime(2023, 10, 24, tzinfo=dt.UTC),
    )
    client.force_login(user)

    response = cancel_batch_export_run(client, team.pk, batch_export.id, run.id)

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == "Cannot cancel a run that is in 'Completed' status"

    run.refresh_from_db()
    assert run.status == BatchExportRun.Status.COMPLETED
