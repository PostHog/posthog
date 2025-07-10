import asyncio
import datetime as dt
import time
from unittest.mock import patch

import pytest
from django.test.client import Client as HttpClient

from posthog.api.test.batch_exports.conftest import start_test_worker
from posthog.api.test.batch_exports.fixtures import create_organization
from posthog.api.test.batch_exports.operations import (
    backfill_batch_export_ok,
    cancel_batch_export_backfill_ok,
    create_batch_export_ok,
    get_batch_export_backfill_ok,
    list_batch_export_backfills_ok,
)
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.test.base import _create_event


def wait_for_backfill_creation(client: HttpClient, team_id: int, batch_export_id: str):
    total = 0
    timeout = 30
    while total < timeout:
        response = list_batch_export_backfills_ok(client, team_id, batch_export_id)
        backfills = response["results"]
        if len(backfills) == 0:
            time.sleep(1)
            total += 1
        else:
            return backfills[0]

    raise Exception("Backfill not found")


@pytest.mark.django_db(transaction=True)
def test_cancelling_a_batch_export_backfill(client: HttpClient, temporal):
    """Test cancelling a BatchExportBackfill."""
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

    with patch("products.batch_exports.backend.temporal.s3_batch_export.Producer.start") as mock_producer_start:
        # Mock the producer to sleep so we can test cancellation
        async def mock_sleep(*args, **kwargs):
            await asyncio.sleep(5)
            return None

        mock_producer_start.side_effect = mock_sleep

        with start_test_worker(temporal):
            batch_export = create_batch_export_ok(
                client,
                team.pk,
                batch_export_data,
            )
            batch_export_id = batch_export["id"]

            start_at = "2023-10-23T00:00:00+00:00"
            end_at = "2023-10-24T00:00:00+00:00"
            # ensure there is data to backfill, otherwise validation will fail
            _create_event(
                team=team,
                event="$pageview",
                distinct_id="person_1",
                timestamp=dt.datetime(2023, 10, 23, 0, 1, 0, tzinfo=dt.UTC),
            )
            backfill_batch_export_ok(client, team.pk, batch_export_id, start_at, end_at)

            # backfill model is created as part of a temporal activity, so we need to wait for it to be created
            backfill_data = wait_for_backfill_creation(client, team.pk, batch_export_id)
            assert backfill_data["status"] == "Running"
            backfill_id = backfill_data["id"]

            data = cancel_batch_export_backfill_ok(client, team.pk, batch_export_id, backfill_id)
            assert data["cancelled"] is True

            backfill_data = get_batch_export_backfill_ok(client, team.pk, batch_export_id, backfill_id)
            assert backfill_data["status"] == "Cancelled"
