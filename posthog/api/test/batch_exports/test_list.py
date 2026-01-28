import pytest
from unittest import mock

from django.test.client import Client as HttpClient

from posthog.api.test.batch_exports.fixtures import create_organization
from posthog.api.test.batch_exports.operations import (
    create_batch_export_ok,
    delete_batch_export_ok,
    list_batch_exports_ok,
)
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user

pytestmark = [
    pytest.mark.django_db,
]


def test_list_batch_exports(client: HttpClient, organization, team, user):
    """
    Should be able to list batch exports.
    """
    client.force_login(user)

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

    first_export = create_batch_export_ok(client, team.pk, batch_export_data)
    second_export = create_batch_export_ok(client, team.pk, batch_export_data)

    response = list_batch_exports_ok(client, team.pk)
    assert len(response["results"]) == 2

    # Deleted batch exports should not be returned.
    delete_batch_export_ok(client, team.pk, first_export["id"])
    response = list_batch_exports_ok(client, team.pk)
    assert len(response["results"]) == 1

    delete_batch_export_ok(client, team.pk, second_export["id"])
    response = list_batch_exports_ok(client, team.pk)
    assert len(response["results"]) == 0


def test_cannot_list_batch_exports_for_other_organizations(client: HttpClient, organization, team, user):
    """
    Should not be able to list batch exports for other teams.
    """
    other_organization = create_organization("Other Test Org")
    other_team = create_team(other_organization)
    other_user = create_user("another-test@user.com", "Another Test User", other_organization)

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

    client.force_login(user)
    create_batch_export_ok(client, team.pk, batch_export_data)
    create_batch_export_ok(client, team.pk, batch_export_data)

    # Make sure we can list batch exports for our own team.
    response = list_batch_exports_ok(client, team.pk)
    assert len(response["results"]) == 2

    client.force_login(other_user)
    response = list_batch_exports_ok(client, other_team.pk)
    assert len(response["results"]) == 0


def test_list_is_partitioned_by_team(client: HttpClient, organization, team, user):
    """
    Should be able to list batch exports for a specific team.
    """
    another_team = create_team(organization)

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

    client.force_login(user)
    create_batch_export_ok(client, team.pk, batch_export_data)
    create_batch_export_ok(client, team.pk, batch_export_data)

    # Make sure we can list batch exports for that team.
    response = list_batch_exports_ok(client, team.pk)
    assert len(response["results"]) == 2

    # Make sure we can't see these batch exports for the other team.
    response = list_batch_exports_ok(client, another_team.pk)
    assert len(response["results"]) == 0


@pytest.fixture
def enable_backfilling_workflows(team):
    with mock.patch(
        "posthog.batch_exports.http.posthoganalytics.feature_enabled", return_value=True
    ) as feature_enabled:
        yield

        feature_enabled.assert_any_call(
            "backfill-workflows-destination",
            str(team.uuid),
            groups={"organization": str(team.organization.id)},
            group_properties={
                "organization": {
                    "id": str(team.organization.id),
                    "created_at": team.organization.created_at,
                }
            },
            send_feature_flag_events=False,
        )


def test_list_filters_workflows_destination(client: HttpClient, organization, team, user, enable_backfilling_workflows):
    """
    Workflows should be filtered out from the list.
    """
    client.force_login(user)

    s3_destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
        },
    }

    s3_batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": s3_destination_data,
        "interval": "hour",
    }

    realtime_destination_data = {
        "type": "Workflows",
        "config": {},
    }

    realtime_batch_export_data = {
        "name": "my-realtime-destination",
        "destination": realtime_destination_data,
        "interval": "hour",
    }

    create_batch_export_ok(client, team.pk, s3_batch_export_data)
    create_batch_export_ok(client, team.pk, realtime_batch_export_data)

    response = list_batch_exports_ok(client, team.pk)
    assert len(response["results"]) == 1
    assert response["results"][0]["destination"]["type"] == "S3"
