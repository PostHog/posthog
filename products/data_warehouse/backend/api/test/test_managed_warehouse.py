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
