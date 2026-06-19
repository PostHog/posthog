from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from rest_framework.response import Response

from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam, DuckLakeBackfill
from posthog.models import Organization, Team

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
    team = Team.objects.create(organization=org)
    mock_request.return_value = Response(
        {"status": "provisioning started", "org": str(org.id), "username": "root", "password": "secret"},
        status=202,
    )

    resp = managed_warehouse.provision(org.id, "my-warehouse", team.id)

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
def test_provision_enables_backfill_for_calling_team_only(mock_request: MagicMock) -> None:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org, name="Production")
    other_team = Team.objects.create(organization=org)
    mock_request.return_value = Response(
        {"status": "provisioning started", "org": str(org.id), "username": "root", "password": "secret"},
        status=202,
    )

    managed_warehouse.provision(org.id, "my-warehouse", team.id)

    backfill = DuckLakeBackfill.objects.get(team_id=team.id)
    assert backfill.enabled is True
    # New provisions set a per-environment suffix derived from the project name.
    assert backfill.events_table_suffix == "production"
    assert not DuckLakeBackfill.objects.filter(team_id=other_team.id).exists()

    # Provision also records first-class duckling membership for the provisioning team only.
    server = DuckgresServer.objects.get(organization_id=org.id)
    assert DuckgresServerTeam.objects.filter(server=server, team_id=team.id).exists()
    assert not DuckgresServerTeam.objects.filter(team_id=other_team.id).exists()


@pytest.mark.django_db
@override_settings(CLOUD_DEPLOYMENT="EU", DUCKGRES_PG_PORT=5432)
@patch("products.data_warehouse.backend.api.managed_warehouse._request")
def test_provision_persists_server_without_bucket_when_region_unsupported(mock_request: MagicMock) -> None:
    # EU has no managed-warehouse bucket convention, so bucket derivation raises. The
    # connection row (with the one-time password) must still be persisted.
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    mock_request.return_value = Response(
        {"status": "provisioning started", "org": str(org.id), "username": "root", "password": "secret"},
        status=202,
    )

    resp = managed_warehouse.provision(org.id, "my-warehouse", team.id)

    assert resp.status_code == 202
    server = DuckgresServer.objects.get(organization_id=org.id)
    assert server.password == "secret"
    assert server.bucket is None


@pytest.mark.django_db
@patch("products.data_warehouse.backend.api.managed_warehouse._request")
def test_provision_does_not_persist_on_failure(mock_request: MagicMock) -> None:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    mock_request.return_value = Response({"error": "boom"}, status=500)

    resp = managed_warehouse.provision(org.id, "my-warehouse", team.id)

    assert resp.status_code == 500
    assert not DuckgresServer.objects.filter(organization_id=org.id).exists()
    assert not DuckLakeBackfill.objects.filter(team_id=team.id).exists()


def _provisioned_org() -> tuple[Organization, Team, DuckgresServer]:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org, name="Env")
    server = DuckgresServer.objects.create(
        organization=org, host="h", port=5432, database="ducklake", username="root", password="x"
    )
    return org, team, server


@pytest.mark.django_db
@patch("products.data_warehouse.backend.api.managed_warehouse.is_enabled", return_value=True)
def test_enable_backfill_creates_backfill_and_membership(mock_enabled: MagicMock) -> None:
    org, team, server = _provisioned_org()

    resp = managed_warehouse.enable_backfill(org.id, team.id, "My Events")

    assert resp.status_code == 200
    assert resp.data == {"enabled": True, "events_table_suffix": "my_events"}

    backfill = DuckLakeBackfill.objects.get(team_id=team.id)
    assert backfill.enabled is True
    assert backfill.events_table_suffix == "my_events"
    assert DuckgresServerTeam.objects.filter(server=server, team_id=team.id).exists()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.api.managed_warehouse.is_enabled", return_value=True)
def test_enable_backfill_requires_name(mock_enabled: MagicMock) -> None:
    org, team, _ = _provisioned_org()

    resp = managed_warehouse.enable_backfill(org.id, team.id, "")

    assert resp.status_code == 400
    assert not DuckLakeBackfill.objects.filter(team_id=team.id).exists()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.api.managed_warehouse.is_enabled", return_value=True)
def test_enable_backfill_rejects_duplicate_suffix_in_org(mock_enabled: MagicMock) -> None:
    org, team_a, _ = _provisioned_org()
    team_b = Team.objects.create(organization=org, name="Env B")
    DuckLakeBackfill.objects.create(team=team_a, events_table_suffix="shared")

    resp = managed_warehouse.enable_backfill(org.id, team_b.id, "shared")

    assert resp.status_code == 400
    assert not DuckLakeBackfill.objects.filter(team_id=team_b.id).exists()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.api.managed_warehouse.is_enabled", return_value=True)
def test_enable_backfill_without_provisioned_server(mock_enabled: MagicMock) -> None:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org, name="Env")

    resp = managed_warehouse.enable_backfill(org.id, team.id, "events")

    assert resp.status_code == 400
    assert "provision" in resp.data["error"].lower()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.api.managed_warehouse.is_enabled", return_value=False)
def test_enable_backfill_gated_on_feature_flag(mock_enabled: MagicMock) -> None:
    org, team, _ = _provisioned_org()

    resp = managed_warehouse.enable_backfill(org.id, team.id, "events")

    assert resp.status_code == 403
    assert not DuckLakeBackfill.objects.filter(team_id=team.id).exists()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.api.managed_warehouse.is_enabled", return_value=True)
def test_enable_backfill_is_idempotent_for_team(mock_enabled: MagicMock) -> None:
    org, team, server = _provisioned_org()

    managed_warehouse.enable_backfill(org.id, team.id, "first")
    resp = managed_warehouse.enable_backfill(org.id, team.id, "second")

    assert resp.status_code == 200
    assert DuckLakeBackfill.objects.filter(team_id=team.id).count() == 1
    assert DuckgresServerTeam.objects.filter(team_id=team.id).count() == 1
    assert DuckLakeBackfill.objects.get(team_id=team.id).events_table_suffix == "second"
