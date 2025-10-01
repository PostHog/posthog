import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.api.test.batch_exports.fixtures import create_organization
from posthog.api.test.batch_exports.operations import create_batch_export_ok, get_batch_export
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user

pytestmark = [
    pytest.mark.django_db,
]


def test_can_get_exports_for_your_organizations(client: HttpClient, temporal, organization, team, user):
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

    response = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    response = get_batch_export(client, team.pk, response["id"])
    assert response.status_code == status.HTTP_200_OK, response.json()

    batch_export = response.json()

    # Check that the destination config is returned, except for aws_access_key_id and aws_secret_access_key.
    assert batch_export["destination"]["config"] == {
        "bucket_name": "my-production-s3-bucket",
        "region": "us-east-1",
        "prefix": "posthog-events/",
    }


def test_cannot_get_exports_for_other_organizations(client: HttpClient, temporal, organization, team, user):
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

    another_organization = create_organization("Another Org")
    another_user = create_user("another-test@user.com", "Another Test User", another_organization)

    client.force_login(user)
    response = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    client.force_login(another_user)
    response = get_batch_export(client, team.pk, response["id"])
    assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()


def test_batch_exports_are_partitioned_by_team(client: HttpClient, temporal, organization, team, user):
    """
    You shouldn't be able to fetch a BatchExport by id, via a team that it
    doesn't belong to.
    """
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

    another_team = create_team(organization)

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
