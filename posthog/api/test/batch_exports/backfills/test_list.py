import datetime as dt

import pytest
from django.test.client import Client as HttpClient

from posthog.api.test.batch_exports.conftest import start_test_worker_async
from posthog.api.test.batch_exports.fixtures import create_organization
from posthog.api.test.batch_exports.operations import (
    backfill_batch_export_ok,
    create_batch_export_ok,
    list_batch_export_backfills_ok,
)
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.temporal.common.client import sync_connect
from posthog.test.base import _create_event

pytestmark = [
    pytest.mark.django_db,
]


def create_batch_export(client: HttpClient, team_id: int):
    """We're not too concerned with the details of the batch export itself, so we create one with some dummy data."""
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
    return create_batch_export_ok(client, team_id, batch_export_data)


def test_list_batch_exports(client: HttpClient):
    """
    Should be able to list batch exports.
    """
    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    temporal = sync_connect()
    with start_test_worker_async(temporal):
        batch_export = create_batch_export(client, team.pk)
        batch_export_id = batch_export["id"]

        # create 2 backfills
        # (ensure there is data to backfill, otherwise validation will fail)
        _create_event(
            team=team,
            event="$pageview",
            distinct_id="person_1",
            timestamp=dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
        )
        backfill_batch_export_ok(
            client, team.pk, batch_export_id, "2021-01-01T00:00:00+00:00", "2021-01-01T01:00:00+00:00"
        )
        backfill_batch_export_ok(
            client, team.pk, batch_export_id, "2021-01-01T01:00:00+00:00", "2021-01-01T03:00:00+00:00"
        )

        response = list_batch_export_backfills_ok(client, team.pk, batch_export_id)
        assert len(response["results"]) == 2


# def test_cannot_list_batch_exports_for_other_organizations(client: HttpClient):
#     """
#     Should not be able to list batch exports for other teams.
#     """
#     organization = create_organization("Test Org")
#     team = create_team(organization)
#     user = create_user("test@user.com", "Test User", organization)

#     other_organization = create_organization("Other Test Org")
#     other_team = create_team(other_organization)
#     other_user = create_user("another-test@user.com", "Another Test User", other_organization)

#     destination_data = {
#         "type": "S3",
#         "config": {
#             "bucket_name": "my-production-s3-bucket",
#             "region": "us-east-1",
#             "prefix": "posthog-events/",
#             "aws_access_key_id": "abc123",
#             "aws_secret_access_key": "secret",
#         },
#     }

#     batch_export_data = {
#         "name": "my-production-s3-bucket-destination",
#         "destination": destination_data,
#         "interval": "hour",
#     }

#     client.force_login(user)
#     create_batch_export_ok(client, team.pk, batch_export_data)
#     create_batch_export_ok(client, team.pk, batch_export_data)

#     # Make sure we can list batch exports for our own team.
#     response = list_batch_exports_ok(client, team.pk)
#     assert len(response["results"]) == 2

#     client.force_login(other_user)
#     response = list_batch_exports_ok(client, other_team.pk)
#     assert len(response["results"]) == 0


# def test_list_is_partitioned_by_team(client: HttpClient):
#     """
#     Should be able to list batch exports for a specific team.
#     """
#     organization = create_organization("Test Org")
#     team = create_team(organization)
#     another_team = create_team(organization)
#     user = create_user("test@user.com", "Test User", organization)

#     destination_data = {
#         "type": "S3",
#         "config": {
#             "bucket_name": "my-production-s3-bucket",
#             "region": "us-east-1",
#             "prefix": "posthog-events/",
#             "aws_access_key_id": "abc123",
#             "aws_secret_access_key": "secret",
#         },
#     }

#     batch_export_data = {
#         "name": "my-production-s3-bucket-destination",
#         "destination": destination_data,
#         "interval": "hour",
#     }

#     client.force_login(user)
#     create_batch_export_ok(client, team.pk, batch_export_data)
#     create_batch_export_ok(client, team.pk, batch_export_data)

#     # Make sure we can list batch exports for that team.
#     response = list_batch_exports_ok(client, team.pk)
#     assert len(response["results"]) == 2

#     # Make sure we can't see these batch exports for the other team.
#     response = list_batch_exports_ok(client, another_team.pk)
#     assert len(response["results"]) == 0
