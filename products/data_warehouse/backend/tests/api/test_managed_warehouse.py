from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework.response import Response

from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam
from posthog.models import Organization, Team

from products.data_warehouse.backend.presentation.views import managed_warehouse


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.posthoganalytics.feature_enabled")
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
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_provision_persists_duckgres_server_on_success(mock_request: MagicMock) -> None:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    mock_request.return_value = Response(
        {"status": "provisioning started", "org": str(org.id), "username": "root", "password": "secret"},
        status=202,
    )

    resp = managed_warehouse.provision(org.id, "my-warehouse", team.id, "events")

    assert resp.status_code == 202
    server = DuckgresServer.objects.get(organization_id=org.id)
    assert server.host == "my-warehouse.dw.us.postwh.com"
    assert server.database == "ducklake"
    assert server.username == "root"
    assert server.password == "secret"
    # No bucket in the provision response → column left unset. There is no local
    # derivation fallback anymore; the control plane is the only source of the name
    # and status_for() self-heals the row once the CP reports it.
    assert server.bucket is None
    assert server.bucket_region is None


@pytest.mark.django_db
@override_settings(CLOUD_DEPLOYMENT="US", DUCKGRES_PG_PORT=5432)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_provision_sends_default_team_id_to_control_plane(mock_request: MagicMock) -> None:
    # duckgres denies a provision without a default team, so the provisioning team must be
    # forwarded as default_team_id in the outbound body.
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    mock_request.return_value = Response(
        {"status": "provisioning started", "org": str(org.id), "username": "root", "password": "secret"},
        status=202,
    )

    managed_warehouse.provision(org.id, "my-warehouse", team.id, "events")

    json_body = mock_request.call_args.kwargs["json_body"]
    assert json_body["default_team_id"] == team.id


@parameterized.expand(
    [
        ("US", "posthog-duckling-0194d6405db400006cde48d6114c0f99-mw-prod-us", "us-east-1"),
        ("EU", "posthog-duckling-0194d6405db400006cde48d6114c0f99-mw-prod-eu", "eu-central-1"),
    ]
)
@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_provision_persists_bucket_returned_by_control_plane(
    deployment: str, cp_bucket: str, expected_region: str, mock_request: MagicMock
) -> None:
    # When the control plane returns the authoritative bucket name, persist it
    # verbatim instead of re-deriving — the CP owns the naming rule (it pins the
    # same name on the Duckling CR), and the local derivation has drifted from it.
    # A CP response without a region falls back to the deployment's home region.
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
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

    with override_settings(CLOUD_DEPLOYMENT=deployment, DUCKGRES_PG_PORT=5432):
        resp = managed_warehouse.provision(org.id, "my-warehouse", team.id, "events")

    assert resp.status_code == 202
    server = DuckgresServer.objects.get(organization_id=org.id)
    # Verbatim, not the locally-derived f"posthog-duckling-{org.id}-prod-us".
    assert server.bucket == cp_bucket
    assert server.bucket_region == expected_region


@pytest.mark.django_db
@override_settings(CLOUD_DEPLOYMENT="US", DUCKGRES_PG_PORT=5432)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_provision_enables_backfill_for_calling_team_only(mock_request: MagicMock) -> None:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    other_team = Team.objects.create(organization=org)
    mock_request.return_value = Response(
        {"status": "provisioning started", "org": str(org.id), "username": "root", "password": "secret"},
        status=202,
    )

    managed_warehouse.provision(org.id, "my-warehouse", team.id, "prod_events")

    # Provision records first-class duckling membership + backfill for the provisioning team only.
    server = DuckgresServer.objects.get(organization_id=org.id)
    link = DuckgresServerTeam.objects.get(server=server, team_id=team.id)
    assert link.backfill_enabled is True
    # New provisions set the per-environment suffix from the admin-provided table name.
    assert link.table_suffix == "prod_events"
    assert not DuckgresServerTeam.objects.filter(team_id=other_team.id).exists()


@pytest.mark.django_db
@override_settings(CLOUD_DEPLOYMENT="EU", DUCKGRES_PG_PORT=5432)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_provision_on_eu_deployment_persists_eu_host(mock_request: MagicMock) -> None:
    # An EU deployment must present the eu.postwh.com zone in the persisted connection.
    # A CP response without a bucket leaves the column unset here too.
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    mock_request.return_value = Response(
        {"status": "provisioning started", "org": str(org.id), "username": "root", "password": "secret"},
        status=202,
    )

    resp = managed_warehouse.provision(org.id, "my-warehouse", team.id, "events")

    assert resp.status_code == 202
    server = DuckgresServer.objects.get(organization_id=org.id)
    assert server.host == "my-warehouse.dw.eu.postwh.com"
    assert server.password == "secret"
    assert server.bucket is None


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_provision_does_not_persist_on_failure(mock_request: MagicMock) -> None:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    mock_request.return_value = Response({"error": "boom"}, status=500)

    resp = managed_warehouse.provision(org.id, "my-warehouse", team.id, "events")

    assert resp.status_code == 500
    assert not DuckgresServer.objects.filter(organization_id=org.id).exists()
    assert not DuckgresServerTeam.objects.filter(team_id=team.id).exists()


@pytest.mark.django_db
@override_settings(CLOUD_DEPLOYMENT="US")
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
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
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
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
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_status_for_refuses_to_reconcile_on_org_mismatch(mock_request: MagicMock) -> None:
    # A status whose org_id disagrees with the requested org must never overwrite
    # this tenant's bucket — that would redirect backfill to another org's bucket.
    org = Organization.objects.create(name="Org")
    DuckgresServer.objects.create(
        organization_id=org.id,
        host="h",
        port=5432,
        database="ducklake",
        username="root",
        password="pw",
        bucket="posthog-duckling-mine-mw-prod-us",
    )
    mock_request.return_value = Response(
        {
            "org_id": "00000000-0000-0000-0000-000000000000",
            "state": "ready",
            "bucket": "posthog-duckling-other-mw-prod-us",
        },
        status=200,
    )

    managed_warehouse.status_for(org.id)

    assert DuckgresServer.objects.get(organization_id=org.id).bucket == "posthog-duckling-mine-mw-prod-us"


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
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


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_status_for_self_heals_stale_region_only(mock_request: MagicMock) -> None:
    # Bucket already correct but region drifted — the row must still be repaired.
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
        bucket_region="eu-west-1",  # stale
    )
    mock_request.return_value = Response(
        {"org_id": str(org.id), "state": "ready", "bucket": bucket, "bucket_region": "us-east-1"}, status=200
    )

    managed_warehouse.status_for(org.id)

    server = DuckgresServer.objects.get(organization_id=org.id)
    assert server.bucket == bucket
    assert server.bucket_region == "us-east-1"


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_status_for_strips_bucket_from_response(mock_request: MagicMock) -> None:
    # The bucket is internal infra detail — never part of the UI-facing status body.
    org = Organization.objects.create(name="Org")
    mock_request.return_value = Response(
        {"org_id": str(org.id), "state": "ready", "bucket": "posthog-duckling-x-mw-prod-us"}, status=200
    )

    resp = managed_warehouse.status_for(org.id)

    assert "bucket" not in resp.data
    assert "bucket_region" not in resp.data


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=False)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.internal_requests")
@override_settings(DUCKGRES_API_URL="http://duckgres.invalid", DUCKGRES_INTERNAL_SECRET="s")
def test_cp_bucket_for_bypasses_feature_gate_and_reconciles(mock_internal: MagicMock, _mock_enabled: MagicMock) -> None:
    # Backend path: the user-facing flag is OFF, but cp_bucket_for must still reach the
    # control plane (require_enabled=False) and return + reconcile the authoritative bucket.
    org = Organization.objects.create(name="Org")
    DuckgresServer.objects.create(
        organization_id=org.id, host="h", port=5432, database="ducklake", username="root", password="pw", bucket="stale"
    )
    cp_bucket = "posthog-duckling-0194d6405db400006cde48d6114c0f99-mw-prod-us"
    http_resp = MagicMock(status_code=200)
    http_resp.json.return_value = {"org_id": str(org.id), "state": "ready", "bucket": cp_bucket}
    mock_internal.request.return_value = http_resp

    result = managed_warehouse.cp_bucket_for(org.id)

    assert result == cp_bucket
    assert DuckgresServer.objects.get(organization_id=org.id).bucket == cp_bucket


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_provision_rejects_invalid_table_name(mock_request: MagicMock) -> None:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)

    for bad_name in ("", "My Project", "my-project"):
        resp = managed_warehouse.provision(org.id, "my-warehouse", team.id, bad_name)
        assert resp.status_code == 400, bad_name

    # Rejected up front, before the duckgres provision call.
    mock_request.assert_not_called()


def _provisioned_org() -> tuple[Organization, Team, DuckgresServer]:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org, name="Env")
    server = DuckgresServer.objects.create(
        organization=org, host="h", port=5432, database="ducklake", username="root", password="x"
    )
    return org, team, server


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.internal_requests")
@override_settings(DUCKGRES_API_URL="http://duckgres.invalid", DUCKGRES_INTERNAL_SECRET="s")
def test_cp_bucket_for_rejects_org_mismatch(mock_internal: MagicMock, _mock_enabled: MagicMock) -> None:
    # A status body for a different org must yield no bucket and touch no row.
    org = Organization.objects.create(name="Org")
    DuckgresServer.objects.create(
        organization_id=org.id, host="h", port=5432, database="ducklake", username="root", password="pw", bucket="mine"
    )
    http_resp = MagicMock(status_code=200)
    http_resp.json.return_value = {
        "org_id": "00000000-0000-0000-0000-000000000000",
        "state": "ready",
        "bucket": "other",
    }
    mock_internal.request.return_value = http_resp

    result = managed_warehouse.cp_bucket_for(org.id)

    assert result is None
    assert DuckgresServer.objects.get(organization_id=org.id).bucket == "mine"


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_cp_bucket_for_returns_none_when_cp_has_no_bucket(mock_request: MagicMock) -> None:
    org = Organization.objects.create(name="Org")
    mock_request.return_value = Response({"org_id": str(org.id), "state": "ready"}, status=200)

    assert managed_warehouse.cp_bucket_for(org.id) is None


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
def test_enable_backfill_creates_backfill_and_membership(mock_enabled: MagicMock) -> None:
    org, team, server = _provisioned_org()

    resp = managed_warehouse.enable_backfill(org.id, team.id, "my_events")

    assert resp.status_code == 200
    assert resp.data == {"enabled": True, "table_suffix": "my_events"}

    link = DuckgresServerTeam.objects.get(server=server, team_id=team.id)
    assert link.backfill_enabled is True
    assert link.table_suffix == "my_events"


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
def test_enable_backfill_rejects_invalid_name(mock_enabled: MagicMock) -> None:
    org, team, _ = _provisioned_org()

    for bad_name in ("", "My Project", "my-project"):
        resp = managed_warehouse.enable_backfill(org.id, team.id, bad_name)
        assert resp.status_code == 400, bad_name

    assert not DuckgresServerTeam.objects.filter(team_id=team.id).exists()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
def test_enable_backfill_rejects_duplicate_suffix_in_org(mock_enabled: MagicMock) -> None:
    org, team_a, server = _provisioned_org()
    team_b = Team.objects.create(organization=org, name="Env B")
    DuckgresServerTeam.objects.create(server=server, team=team_a, table_suffix="shared")

    resp = managed_warehouse.enable_backfill(org.id, team_b.id, "shared")

    assert resp.status_code == 400
    assert not DuckgresServerTeam.objects.filter(team_id=team_b.id).exists()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
def test_enable_backfill_without_provisioned_server(mock_enabled: MagicMock) -> None:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org, name="Env")

    resp = managed_warehouse.enable_backfill(org.id, team.id, "events")

    assert resp.status_code == 400
    assert "provision" in resp.data["error"].lower()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=False)
def test_enable_backfill_gated_on_feature_flag(mock_enabled: MagicMock) -> None:
    org, team, _ = _provisioned_org()

    resp = managed_warehouse.enable_backfill(org.id, team.id, "events")

    assert resp.status_code == 403
    assert not DuckgresServerTeam.objects.filter(team_id=team.id).exists()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
def test_enable_backfill_same_name_is_idempotent(mock_enabled: MagicMock) -> None:
    org, team, _ = _provisioned_org()

    managed_warehouse.enable_backfill(org.id, team.id, "first")
    resp = managed_warehouse.enable_backfill(org.id, team.id, "first")

    assert resp.status_code == 200
    assert DuckgresServerTeam.objects.filter(team_id=team.id).count() == 1
    assert DuckgresServerTeam.objects.get(team_id=team.id).table_suffix == "first"


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
def test_enable_backfill_refuses_to_change_an_existing_suffix(mock_enabled: MagicMock) -> None:
    org, team, _ = _provisioned_org()
    managed_warehouse.enable_backfill(org.id, team.id, "first")

    resp = managed_warehouse.enable_backfill(org.id, team.id, "second")

    # Changing a set suffix would split the team's data across two tables — rejected, unchanged.
    assert resp.status_code == 400
    assert DuckgresServerTeam.objects.get(team_id=team.id).table_suffix == "first"


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
def test_enable_backfill_refuses_to_set_a_suffix_on_a_legacy_shared_team(mock_enabled: MagicMock) -> None:
    org, team, server = _provisioned_org()
    # A legacy team already backfilling to the shared tables (NULL suffix), e.g. backfilled by migration.
    DuckgresServerTeam.objects.create(server=server, team=team, backfill_enabled=True, table_suffix=None)

    resp = managed_warehouse.enable_backfill(org.id, team.id, "new_name")

    assert resp.status_code == 400
    assert DuckgresServerTeam.objects.get(team_id=team.id).table_suffix is None
