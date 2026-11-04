from typing import Any

import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.integrations import IntegrationManager, IntegrationRecord
from posthog.models import Team, User

from products.batch_exports.backend.models.batch_export import BatchExport
from products.batch_exports.backend.tests.api.operations import (
    create_batch_export_ok,
    get_batch_export_ok,
    patch_batch_export,
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


def create_copy_batch_export(
    client: HttpClient, team: Team, user: User, copy_inputs: dict[str, Any], integration_pk: int
) -> dict[str, Any]:
    destination_data = {
        "type": "Redshift",
        "config": {
            "database": "my-db",
            "host": "localhost",
            "schema": "public",
            "table_name": "my_events",
            "mode": "COPY",
            "copy_inputs": copy_inputs,
        },
        "integration": integration_pk,
    }
    batch_export_data = {
        "name": "test-redshift-export",
        "destination": destination_data,
        "interval": "hour",
    }
    client.force_login(user)
    return create_batch_export_ok(client, team.pk, batch_export_data)


@pytest.mark.parametrize("field_name", ["authorization", "bucket_credentials"])
@pytest.mark.parametrize(
    "patch_kind",
    ["omit", "bucket", "empty_copy_inputs", "empty_credentials", "unchanged", "integration"],
)
def test_can_patch_redshift_batch_export_with_legacy_copy_credentials(
    client: HttpClient,
    team: Team,
    user: User,
    aws_s3_integration: IntegrationRecord,
    aws_redshift_integration: IntegrationRecord,
    field_name: str,
    patch_kind: str,
) -> None:
    batch_export = create_copy_batch_export(
        client,
        team,
        user,
        {
            "s3_bucket": "test-staging-bucket",
            "region_name": "us-east-1",
            "s3_key_prefix": "posthog-events/",
            "bucket_credentials": aws_s3_integration.id,
            "authorization": aws_s3_integration.id,
        },
        aws_redshift_integration.id,
    )
    destination = (
        BatchExport.objects.select_related("destination").get(id=batch_export["id"], team_id=team.id).destination
    )
    legacy_credentials = {"aws_access_key_id": "test-access-key", "aws_secret_access_key": "test-secret-key"}
    destination.config["copy_inputs"][field_name] = legacy_credentials
    destination.save()

    config: dict[str, Any] = {"table_name": "updated_events"}
    if patch_kind == "bucket":
        config["copy_inputs"] = {"s3_bucket": "updated-test-bucket"}
    elif patch_kind == "empty_copy_inputs":
        config["copy_inputs"] = {}
    elif patch_kind == "empty_credentials":
        config["copy_inputs"] = {field_name: {}}
    elif patch_kind == "unchanged":
        config["copy_inputs"] = {field_name: legacy_credentials}
    elif patch_kind == "integration":
        config["copy_inputs"] = {field_name: aws_s3_integration.id}

    response = patch_batch_export(
        client,
        team.pk,
        batch_export["id"],
        {"destination": {"type": "Redshift", "config": config}},
    )
    assert response.status_code == status.HTTP_200_OK, response.json()

    destination.refresh_from_db()
    assert destination.config["table_name"] == "updated_events"
    if patch_kind == "bucket":
        assert destination.config["copy_inputs"]["s3_bucket"] == "updated-test-bucket"
    if patch_kind == "integration":
        assert int(destination.config["copy_inputs"][field_name]) == aws_s3_integration.id
        batch_export = get_batch_export_ok(client, team.pk, batch_export["id"])
        assert batch_export["destination"]["config"]["copy_inputs"][field_name] == aws_s3_integration.id
    else:
        assert destination.config["copy_inputs"][field_name] == legacy_credentials


@pytest.mark.parametrize(
    "field_name,previous_source",
    [
        ("bucket_credentials", "integration"),
        ("authorization", "integration"),
        ("authorization", "iam_role"),
        ("bucket_credentials", "legacy"),
        ("authorization", "legacy"),
    ],
)
@pytest.mark.parametrize("changed_key", ["aws_access_key_id", "aws_secret_access_key", "both"])
def test_patching_redshift_batch_export_rejects_changed_inline_copy_credentials(
    client: HttpClient,
    team: Team,
    user: User,
    aws_s3_integration: IntegrationRecord,
    aws_redshift_integration: IntegrationRecord,
    field_name: str,
    previous_source: str,
    changed_key: str,
) -> None:
    batch_export = create_copy_batch_export(
        client,
        team,
        user,
        {
            "s3_bucket": "test-staging-bucket",
            "region_name": "us-east-1",
            "s3_key_prefix": "posthog-events/",
            "bucket_credentials": aws_s3_integration.id,
            "authorization": (
                "arn:aws:iam::000000000000:role/test-copy" if previous_source == "iam_role" else aws_s3_integration.id
            ),
        },
        aws_redshift_integration.id,
    )
    destination = (
        BatchExport.objects.select_related("destination").get(id=batch_export["id"], team_id=team.id).destination
    )
    legacy_credentials = {"aws_access_key_id": "test-access-key", "aws_secret_access_key": "test-secret-key"}
    if previous_source == "legacy":
        destination.config["copy_inputs"][field_name] = legacy_credentials
        destination.save()
    destination.refresh_from_db()
    stored_value = destination.config["copy_inputs"][field_name]

    credentials = {
        key: f"changed-{value}" if changed_key in {key, "both"} else value for key, value in legacy_credentials.items()
    }
    if previous_source == "legacy" and changed_key != "both":
        credentials = {changed_key: credentials[changed_key]}
    response = patch_batch_export(
        client,
        team.pk,
        batch_export["id"],
        {"destination": {"type": "Redshift", "config": {"copy_inputs": {field_name: credentials}}}},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    detail = response.json()["detail"]
    assert "AWS S3 integration" in detail
    if previous_source == "integration":
        assert f"Cannot switch '{field_name}' from an integration to inline credentials" in detail
    else:
        assert "Inline AWS access keys are no longer accepted" in detail
    assert all(value not in detail for value in credentials.values())
    destination.refresh_from_db()
    assert destination.config["copy_inputs"][field_name] == stored_value


def test_can_patch_redshift_batch_export_swapping_copy_integration(
    client: HttpClient,
    team: Team,
    user: User,
    aws_s3_integration: IntegrationRecord,
    aws_redshift_integration: IntegrationRecord,
) -> None:
    other_integration = IntegrationManager.aws_s3.credentials.create(
        team_id=team.id,
        external_id="test-aws-2",
        config={"name": "test-aws-2"},
        sensitive_config={"aws_access_key_id": "test-key-2", "aws_secret_access_key": "test-secret-2"},
        created_by_id=user.id,
    )
    batch_export = create_copy_batch_export(
        client,
        team,
        user,
        {
            "s3_bucket": "test-staging-bucket",
            "region_name": "us-east-1",
            "s3_key_prefix": "posthog-events/",
            "bucket_credentials": aws_s3_integration.id,
            "authorization": aws_s3_integration.id,
        },
        aws_redshift_integration.id,
    )

    new_batch_export_data = {
        "destination": {
            "type": "Redshift",
            "config": {
                "copy_inputs": {
                    "bucket_credentials": other_integration.id,
                    "authorization": other_integration.id,
                },
            },
            "integration": aws_redshift_integration.id,
        },
    }

    response = patch_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    assert response.status_code == status.HTTP_200_OK, response.json()

    batch_export = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert batch_export["destination"]["config"]["copy_inputs"]["bucket_credentials"] == other_integration.id
    assert batch_export["destination"]["config"]["copy_inputs"]["authorization"] == other_integration.id
