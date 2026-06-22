from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from rest_framework.response import Response

from posthog.ducklake.models import DuckgresServer
from posthog.models import Organization

from products.data_warehouse.backend.api import managed_warehouse


@patch("products.data_warehouse.backend.api.managed_warehouse.posthoganalytics.feature_enabled")
def test_is_enabled_uses_data_warehouse_scene_flag(mock_feature_enabled: MagicMock) -> None:
    organization_id = uuid4()
    mock_feature_enabled.return_value = True

    assert managed_warehouse.is_enabled(organization_id) is True

    mock_feature_enabled.assert_called_once_with(
        "data-warehouse-scene",
        str(organization_id),
        groups={"organization": str(organization_id)},
        group_properties={"organization": {"id": str(organization_id)}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


@pytest.mark.django_db
@override_settings(CLOUD_DEPLOYMENT="US", DUCKGRES_PG_PORT=5432)
@patch("products.data_warehouse.backend.api.managed_warehouse._request")
def test_provision_persists_duckgres_server_on_success(mock_request: MagicMock) -> None:
    org = Organization.objects.create(name="Org")
    mock_request.return_value = Response(
        {"status": "provisioning started", "org": str(org.id), "username": "root", "password": "secret"},
        status=202,
    )

    resp = managed_warehouse.provision(org.id, "my-warehouse")

    assert resp.status_code == 202
    server = DuckgresServer.objects.get(organization_id=org.id)
    assert server.host == "my-warehouse.dw.us.postwh.com"
    assert server.database == "ducklake"
    assert server.username == "root"
    assert server.password == "secret"
    assert server.bucket == f"posthog-duckling-{org.id}-prod-us"
    assert server.bucket_region == "us-east-1"


@pytest.mark.django_db
@override_settings(CLOUD_DEPLOYMENT="US", DUCKGRES_PG_PORT=5432)
@patch("products.data_warehouse.backend.api.managed_warehouse._request")
def test_provision_persists_bucket_returned_by_control_plane(mock_request: MagicMock) -> None:
    # When the control plane returns the authoritative bucket name, persist it
    # verbatim instead of re-deriving — the CP owns the naming rule (it pins the
    # same name on the Duckling CR), and the local derivation has drifted from it.
    org = Organization.objects.create(name="Org")
    cp_bucket = "posthog-duckling-0194d6405db400006cde48d6114c0f99-mw-prod-us"
    mock_request.return_value = Response(
        {
            "status": "provisioning started",
            "org": str(org.id),
            "username": "root",
            "password": "secret",
            "bucket": cp_bucket,
        },
        status=202,
    )

    resp = managed_warehouse.provision(org.id, "my-warehouse")

    assert resp.status_code == 202
    server = DuckgresServer.objects.get(organization_id=org.id)
    # Verbatim, not the locally-derived f"posthog-duckling-{org.id}-prod-us".
    assert server.bucket == cp_bucket
    assert server.bucket_region == "us-east-1"


@pytest.mark.django_db
@override_settings(CLOUD_DEPLOYMENT="EU", DUCKGRES_PG_PORT=5432)
@patch("products.data_warehouse.backend.api.managed_warehouse._request")
def test_provision_persists_server_without_bucket_when_region_unsupported(mock_request: MagicMock) -> None:
    # EU has no managed-warehouse bucket convention, so bucket derivation raises. The
    # connection row (with the one-time password) must still be persisted.
    org = Organization.objects.create(name="Org")
    mock_request.return_value = Response(
        {"status": "provisioning started", "org": str(org.id), "username": "root", "password": "secret"},
        status=202,
    )

    resp = managed_warehouse.provision(org.id, "my-warehouse")

    assert resp.status_code == 202
    server = DuckgresServer.objects.get(organization_id=org.id)
    assert server.password == "secret"
    assert server.bucket is None


@pytest.mark.django_db
@patch("products.data_warehouse.backend.api.managed_warehouse._request")
def test_provision_does_not_persist_on_failure(mock_request: MagicMock) -> None:
    org = Organization.objects.create(name="Org")
    mock_request.return_value = Response({"error": "boom"}, status=500)

    resp = managed_warehouse.provision(org.id, "my-warehouse")

    assert resp.status_code == 500
    assert not DuckgresServer.objects.filter(organization_id=org.id).exists()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.api.managed_warehouse._request")
def test_status_for_self_heals_stale_bucket(mock_request: MagicMock) -> None:
    # A row with a stale (locally-derived) bucket converges to the CP-reported
    # name on the next status read — no separate backfill needed.
    org = Organization.objects.create(name="Org")
    DuckgresServer.objects.create(
        organization_id=org.id,
        host="h",
        port=5432,
        database="ducklake",
        username="root",
        password="pw",
        bucket="posthog-duckling-stale-prod-us",  # wrong/drifted
    )
    cp_bucket = "posthog-duckling-0194d6405db400006cde48d6114c0f99-mw-prod-us"
    mock_request.return_value = Response({"org_id": str(org.id), "state": "ready", "bucket": cp_bucket}, status=200)

    managed_warehouse.status_for(org.id)

    server = DuckgresServer.objects.get(organization_id=org.id)
    assert server.bucket == cp_bucket
    assert server.bucket_region == "us-east-1"


@pytest.mark.django_db
@patch("products.data_warehouse.backend.api.managed_warehouse._request")
def test_status_for_leaves_matching_bucket_untouched(mock_request: MagicMock) -> None:
    org = Organization.objects.create(name="Org")
    bucket = "posthog-duckling-org-mw-prod-us"
    DuckgresServer.objects.create(
        organization_id=org.id,
        host="h",
        port=5432,
        database="ducklake",
        username="root",
        password="pw",
        bucket=bucket,
    )
    mock_request.return_value = Response({"org_id": str(org.id), "state": "ready", "bucket": bucket}, status=200)

    managed_warehouse.status_for(org.id)

    assert DuckgresServer.objects.get(organization_id=org.id).bucket == bucket


@pytest.mark.django_db
@patch("products.data_warehouse.backend.api.managed_warehouse._request")
def test_status_for_without_bucket_leaves_row_alone(mock_request: MagicMock) -> None:
    # External data stores / pre-backfill ducklings report no bucket — don't blank it.
    org = Organization.objects.create(name="Org")
    DuckgresServer.objects.create(
        organization_id=org.id,
        host="h",
        port=5432,
        database="ducklake",
        username="root",
        password="pw",
        bucket="posthog-duckling-keep-mw-prod-us",
    )
    mock_request.return_value = Response({"org_id": str(org.id), "state": "ready"}, status=200)

    managed_warehouse.status_for(org.id)

    assert DuckgresServer.objects.get(organization_id=org.id).bucket == "posthog-duckling-keep-mw-prod-us"
