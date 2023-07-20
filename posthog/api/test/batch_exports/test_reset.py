import datetime as dt
import time

from django.test.client import Client as HttpClient

from posthog.api.test.batch_exports.conftest import start_test_worker
from posthog.api.test.batch_exports.operations import (
    create_batch_export_ok,
    get_batch_export_runs_ok,
    reset_batch_export_run_ok,
)
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.temporal.client import sync_connect
from posthog.test.base import TransactionTestCase
import pytest


def wait_for_runs(client, team_id, batch_export_id, timeout=10, number_of_runs=1):
    """Wait for BatchExportRuns to be created.

    As these rows are created by Temporal, and the worker is running in a separate thread, we allow it
    to take a few seconds.

    Raises:
        TimeoutError: If there are less than number_of_runs BatchExportRuns after around timeout seconds.

    Returns:
        The BatchExportRuns response.
    """
    start = dt.datetime.utcnow()
    batch_export_runs = get_batch_export_runs_ok(client, team_id, batch_export_id)

    while batch_export_runs["count"] < number_of_runs:
        batch_export_runs = get_batch_export_runs_ok(client, team_id, batch_export_id)
        time.sleep(1)
        if (dt.datetime.utcnow() - start).seconds > timeout:
            raise TimeoutError("BatchExportRuns never created")

    return batch_export_runs


@pytest.mark.usefixtures("client")
class TestReset(TransactionTestCase):
    available_apps = ["posthog"]

    @pytest.fixture(autouse=True)
    def use_test_client(self, client: HttpClient):
        if not client:
            pytest.fail("client fixture is required for this test")
        self.client = client

    def test_can_reset_export_run(self):
        """Test calling the reset endpoint to reset a BatchExportRun a couple of times."""
        temporal = sync_connect()

        destination_data = {
            "type": "S3",
            "config": {
                "bucket_name": "my-production-s3-bucket",
                "region": "us-east-1",
                "prefix": "posthog-events/",
                "batch_window_size": 3600,
                "aws_access_key_id": "abc123",
                "aws_secret_access_key": "secret",
            },
        }

        batch_export_data = {
            "name": "my-production-s3-bucket-destination",
            "destination": destination_data,
            "interval": "hour",
            "trigger_immediately": True,
        }

        organization = create_organization("Test Org")
        team = create_team(organization)
        user = create_user("reset.test@user.com", "Reset test user", organization)
        self.client.force_login(user)

        with start_test_worker(temporal):
            batch_export = create_batch_export_ok(
                self.client,
                team.pk,
                batch_export_data,
            )

            batch_export_runs = wait_for_runs(self.client, team.pk, batch_export["id"])
            assert batch_export_runs["count"] == 1

            first_batch_export_run = batch_export_runs["results"][0]
            reset_batch_export_run_ok(self.client, team.pk, batch_export["id"], first_batch_export_run["id"])

            batch_export_runs = wait_for_runs(self.client, team.pk, batch_export["id"], number_of_runs=2)
            assert batch_export_runs["count"] == 2
            assert batch_export_runs["results"][1] == first_batch_export_run

            reset_batch_export_run_ok(self.client, team.pk, batch_export["id"], first_batch_export_run["id"])

            batch_export_runs = wait_for_runs(self.client, team.pk, batch_export["id"], number_of_runs=3)
            assert batch_export_runs["count"] == 3
            assert batch_export_runs["results"][2] == first_batch_export_run
