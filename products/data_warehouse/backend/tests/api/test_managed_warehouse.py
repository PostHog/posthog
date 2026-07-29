from types import SimpleNamespace
from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework.response import Response

from posthog.ducklake import cp_teams
from posthog.ducklake.models import DuckgresServer
from posthog.models import Organization, Team

from products.data_warehouse.backend.presentation.views import managed_warehouse


@pytest.fixture(autouse=True)
def _onboarding_side_effects():
    """Isolate onboarding's best-effort tail (query-connection setup + earliest-date sync).

    Both are real calls now that they run inline (no dual-write / on_commit), so patch them
    at the facade boundary to keep the control-plane request assertions exact.
    """
    cp_teams.clear_cache()
    with (
        patch("products.data_warehouse.backend.facade.tasks.sync_team_earliest_event_date") as mock_task,
        patch("products.data_warehouse.backend.facade.api.ensure_managed_warehouse_direct_source") as mock_ensure,
    ):
        yield SimpleNamespace(task=mock_task, ensure=mock_ensure)
    cp_teams.clear_cache()


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


@patch("products.data_warehouse.backend.facade.api.update_managed_warehouse_root_password")
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_reset_password_reports_local_persistence_failure(
    mock_request: MagicMock, mock_update_password: MagicMock
) -> None:
    mock_request.return_value = Response({"password": "rotated"}, status=200)
    mock_update_password.side_effect = RuntimeError("database unavailable")

    response = managed_warehouse.reset_password(uuid4())

    assert response.status_code == 500
    assert response.data == {"error": "The password was rotated but could not be saved. Retry the password reset."}


@patch("products.data_warehouse.backend.facade.api.schedule_soft_delete_managed_warehouse_sources")
@patch("products.data_warehouse.backend.facade.api.soft_delete_managed_warehouse_sources")
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_deprovision_schedules_cleanup_retry_when_inline_cleanup_fails(
    mock_request: MagicMock, mock_soft_delete: MagicMock, mock_schedule: MagicMock
) -> None:
    # Deprovision is not re-POSTable (Duckgres 409s once the org leaves a deprovisionable state),
    # so a failed local cleanup must converge on its own instead of asking the operator to retry.
    mock_request.return_value = Response({"status": "deprovisioning started"}, status=202)
    mock_soft_delete.side_effect = RuntimeError("database unavailable")
    organization_id = uuid4()

    response = managed_warehouse.deprovision(organization_id)

    assert response.status_code == 202
    mock_schedule.assert_called_once_with(organization_id=organization_id)


@patch("products.data_warehouse.backend.facade.api.schedule_soft_delete_managed_warehouse_sources")
@patch("products.data_warehouse.backend.facade.api.soft_delete_managed_warehouse_sources")
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_deprovision_reports_when_cleanup_and_its_retry_cannot_be_scheduled(
    mock_request: MagicMock, mock_soft_delete: MagicMock, mock_schedule: MagicMock
) -> None:
    mock_request.return_value = Response({"status": "deprovisioning started"}, status=202)
    mock_soft_delete.side_effect = RuntimeError("database unavailable")
    mock_schedule.side_effect = RuntimeError("broker unavailable")

    response = managed_warehouse.deprovision(uuid4())

    assert response.status_code == 500
    assert response.data == {
        "error": "The warehouse was deprovisioned but its SQL connections could not be removed or scheduled for removal. They must be cleaned up manually."
    }


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
def test_provision_sends_team_id_and_schema_name_to_control_plane(mock_request: MagicMock) -> None:
    # The provisioning team becomes the warehouse's first team via the org-teams API:
    # the outbound body carries team_id + schema_name and never default_team_id (dropped
    # along with duckgres's whole default/billing-team concept).
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    mock_request.return_value = Response(
        {"status": "provisioning started", "org": str(org.id), "username": "root", "password": "secret"},
        status=202,
    )

    managed_warehouse.provision(org.id, "my-warehouse", team.id, "prod_events")

    json_body = mock_request.call_args_list[0].kwargs["json_body"]
    assert json_body["team_id"] == team.id
    assert json_body["schema_name"] == "prod_events"
    assert "default_team_id" not in json_body

    # The provision body cannot carry legacy table names, so the first team's row is
    # completed with a follow-up org-teams upsert — same fields onboard_team writes.
    method, org_id, path = mock_request.call_args_list[1].args
    assert (method, org_id, path) == ("POST", org.id, "/teams")
    teams_body = mock_request.call_args_list[1].kwargs["json_body"]
    assert teams_body == {
        "team_id": team.id,
        "schema_name": "prod_events",
        "events_table_name": "events_prod_events",
        "persons_table_name": "persons_prod_events",
        "schema_data_imports_name": "posthog_data_imports_prod_events",
    }


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_provision_succeeds_even_when_the_team_row_completion_fails(mock_request: MagicMock) -> None:
    # The follow-up upsert is best-effort: the warehouse is already provisioned, so a
    # transient teams-API failure must not fail the provision response.
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    mock_request.side_effect = [
        Response(
            {"status": "provisioning started", "org": str(org.id), "username": "root", "password": "secret"},
            status=202,
        ),
        Response({"error": "store unavailable"}, status=500),
    ]

    resp = managed_warehouse.provision(org.id, "my-warehouse", team.id, "prod_events")

    assert resp.status_code == 202


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
def test_provision_registers_calling_team_only(mock_request: MagicMock, _onboarding_side_effects) -> None:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    Team.objects.create(organization=org)
    mock_request.return_value = Response(
        {"status": "provisioning started", "org": str(org.id), "username": "root", "password": "secret"},
        status=202,
    )

    managed_warehouse.provision(org.id, "my-warehouse", team.id, "prod_events")

    # The control plane creates the provisioning team's row from the provision request itself;
    # locally only that team gets its query connection and earliest-date sync kicked off.
    _onboarding_side_effects.ensure.assert_called_once_with(team_id=team.id, organization_id=org.id)
    _onboarding_side_effects.task.delay.assert_called_once_with(team.id)


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
def test_provision_rejects_invalid_schema_name(mock_request: MagicMock) -> None:
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
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_onboard_team_creates_duckgres_row_with_legacy_names(
    mock_request: MagicMock, _mock_enabled: MagicMock, _onboarding_side_effects
) -> None:
    org, team, _ = _provisioned_org()
    mock_request.side_effect = [
        Response({"teams": []}, status=200),
        Response({"team_id": team.id, "schema_name": "my_events"}, status=200),
    ]

    resp = managed_warehouse.onboard_team(org.id, team.id, "my_events")

    assert resp.status_code == 200
    assert resp.data == {"onboarded": True, "schema_name": "my_events"}

    # duckgres team row created via the org-teams upsert WITH the legacy table names the
    # duckling DAG actually writes today (posthog.events_<suffix> + posthog_data_imports_<suffix>).
    # A row without them describes the derived layout no data lands in yet — the EU
    # placeholder-row bug.
    assert mock_request.call_args_list[0].args == ("GET", org.id, "/teams")
    method, org_id, path = mock_request.call_args_list[1].args
    assert (method, org_id, path) == ("POST", org.id, "/teams")
    assert mock_request.call_args_list[1].kwargs["json_body"] == {
        "team_id": team.id,
        "schema_name": "my_events",
        "events_table_name": "events_my_events",
        "persons_table_name": "persons_my_events",
        "schema_data_imports_name": "posthog_data_imports_my_events",
    }
    # Onboarding's tail: the query connection and the earliest-date sync.
    _onboarding_side_effects.ensure.assert_called_once_with(team_id=team.id, organization_id=org.id)
    _onboarding_side_effects.task.delay.assert_called_once_with(team.id)


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_onboard_team_surfaces_duckgres_schema_conflict(mock_request: MagicMock, _mock_enabled: MagicMock) -> None:
    # duckgres owns cross-team schema uniqueness (it also knows grandfathered schemas) —
    # its 409 must reach the caller as a clear conflict.
    org, team, _ = _provisioned_org()
    mock_request.side_effect = [
        Response({"teams": []}, status=200),
        Response({"error": "schema already in use"}, status=409),
    ]

    resp = managed_warehouse.onboard_team(org.id, team.id, "taken")

    assert resp.status_code == 409
    assert "taken" in resp.data["error"]


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_onboard_team_rejects_invalid_name_before_control_plane(
    mock_request: MagicMock, _mock_enabled: MagicMock
) -> None:
    org, team, _ = _provisioned_org()

    for bad_name in ("", "My Project", "my-project"):
        resp = managed_warehouse.onboard_team(org.id, team.id, bad_name)
        assert resp.status_code == 400, bad_name

    mock_request.assert_not_called()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_onboard_team_without_provisioned_server(mock_request: MagicMock, _mock_enabled: MagicMock) -> None:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org, name="Env")

    resp = managed_warehouse.onboard_team(org.id, team.id, "events")

    assert resp.status_code == 400
    assert "provision" in resp.data["error"].lower()
    mock_request.assert_not_called()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=False)
def test_onboard_team_gated_on_feature_flag(mock_enabled: MagicMock) -> None:
    org, team, _ = _provisioned_org()

    resp = managed_warehouse.onboard_team(org.id, team.id, "events")

    assert resp.status_code == 403


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_onboard_team_same_name_is_idempotent(
    mock_request: MagicMock, _mock_enabled: MagicMock, _onboarding_side_effects
) -> None:
    # The CP POST is an upsert, so an already-onboarded team must not re-POST (a hand-set
    # row's overrides would be clobbered) — but re-onboarding with the current name still
    # succeeds and re-runs the best-effort tail.
    org, team, _ = _provisioned_org()
    mock_request.return_value = Response({"teams": [{"team_id": team.id, "schema_name": "first"}]}, status=200)

    resp = managed_warehouse.onboard_team(org.id, team.id, "first")

    assert resp.status_code == 200
    assert resp.data == {"onboarded": True, "schema_name": "first"}
    assert [c.args[0] for c in mock_request.call_args_list] == ["GET"]
    _onboarding_side_effects.ensure.assert_called_once_with(team_id=team.id, organization_id=org.id)


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_onboard_team_refuses_to_change_an_existing_schema(mock_request: MagicMock, _mock_enabled: MagicMock) -> None:
    # Changing a set schema would split the team's data across two tables — rejected before
    # the upsert, so the duckgres row keeps its schema.
    org, team, _ = _provisioned_org()
    mock_request.return_value = Response(
        {"teams": [{"team_id": team.id, "schema_name": "first", "events_table_name": "events_first"}]}, status=200
    )

    resp = managed_warehouse.onboard_team(org.id, team.id, "second")

    assert resp.status_code == 400
    assert "events_first" in resp.data["error"]
    assert [c.args[0] for c in mock_request.call_args_list] == ["GET"]


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_onboard_team_refuses_to_rename_a_legacy_shared_team(mock_request: MagicMock, _mock_enabled: MagicMock) -> None:
    org, team, _ = _provisioned_org()
    # A legacy team pinned to the shared tables (grandfathered row).
    mock_request.return_value = Response(
        {"teams": [{"team_id": team.id, "schema_name": f"team_{team.id}", "events_table_name": "events"}]},
        status=200,
    )

    resp = managed_warehouse.onboard_team(org.id, team.id, "new_name")

    assert resp.status_code == 400
    assert "shared tables" in resp.data["error"]
    assert [c.args[0] for c in mock_request.call_args_list] == ["GET"]


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_onboard_team_fails_retryably_when_control_plane_unreachable(
    mock_request: MagicMock, _mock_enabled: MagicMock
) -> None:
    # The write-once guard needs the CP row list; without it the upsert could silently move
    # an existing schema, so the onboard fails with a retry error instead.
    org, team, _ = _provisioned_org()
    mock_request.return_value = Response({"error": "unreachable"}, status=502)

    resp = managed_warehouse.onboard_team(org.id, team.id, "my_events")

    assert resp.status_code == 502
    assert "try again" in resp.data["error"].lower()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_onboard_team_survives_direct_source_failure(
    mock_request: MagicMock, _mock_enabled: MagicMock, _onboarding_side_effects
) -> None:
    # The query connection is a best-effort convenience; a failure must never fail onboarding.
    org, team, _ = _provisioned_org()
    mock_request.side_effect = [
        Response({"teams": []}, status=200),
        Response({"team_id": team.id, "schema_name": "my_events"}, status=200),
    ]
    _onboarding_side_effects.ensure.side_effect = Exception("boom")

    resp = managed_warehouse.onboard_team(org.id, team.id, "my_events")

    assert resp.status_code == 200


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.internal_requests")
@override_settings(DUCKGRES_API_URL="http://duckgres.invalid", DUCKGRES_INTERNAL_SECRET="s")
def test_delete_org_issues_delete_to_org_root(mock_internal: MagicMock, _mock_enabled: MagicMock) -> None:
    # Guards the empty-path branch in _request: delete_org must hit the org resource itself,
    # /api/v1/orgs/{org}, not a suffixed org path or the global /api/v1/ route.
    org_id = uuid4()
    mock_internal.request.return_value = MagicMock(status_code=200, **{"json.return_value": {"status": "deleted"}})

    resp = managed_warehouse.delete_org(org_id)

    assert resp.status_code == 200
    method, url = mock_internal.request.call_args.args
    assert method == "DELETE"
    assert url == f"http://duckgres.invalid/api/v1/orgs/{org_id}"


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.internal_requests")
@override_settings(DUCKGRES_API_URL="http://duckgres.invalid", DUCKGRES_INTERNAL_SECRET="s")
def test_list_teams_hits_org_teams_route(mock_internal: MagicMock, _mock_enabled: MagicMock) -> None:
    org_id = uuid4()
    mock_internal.request.return_value = MagicMock(status_code=200, **{"json.return_value": []})

    resp = managed_warehouse.list_teams(org_id)

    assert resp.status_code == 200
    method, url = mock_internal.request.call_args.args
    assert method == "GET"
    assert url == f"http://duckgres.invalid/api/v1/orgs/{org_id}/teams"


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.internal_requests")
@override_settings(DUCKGRES_API_URL="http://duckgres.invalid", DUCKGRES_INTERNAL_SECRET="s")
def test_create_team_posts_upsert_with_only_set_optional_fields(
    mock_internal: MagicMock, _mock_enabled: MagicMock
) -> None:
    # Unset legacy fields must be omitted entirely — sending them as null would make duckgres
    # treat a derived-layout team as explicitly named.
    org_id = uuid4()
    mock_internal.request.return_value = MagicMock(status_code=200, **{"json.return_value": {}})

    resp = managed_warehouse.create_team(
        org_id, 42, "my_schema", events_table_name="events_my", persons_table_name="persons_my"
    )

    assert resp.status_code == 200
    method, url = mock_internal.request.call_args.args
    assert method == "POST"
    assert url == f"http://duckgres.invalid/api/v1/orgs/{org_id}/teams"
    assert mock_internal.request.call_args.kwargs["json"] == {
        "team_id": 42,
        "schema_name": "my_schema",
        "events_table_name": "events_my",
        "persons_table_name": "persons_my",
    }


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.internal_requests")
def test_create_team_rejects_invalid_schema_name(mock_internal: MagicMock, _mock_enabled: MagicMock) -> None:
    resp = managed_warehouse.create_team(uuid4(), 42, "Bad Name")

    assert resp.status_code == 400
    mock_internal.request.assert_not_called()


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.internal_requests")
@override_settings(DUCKGRES_API_URL="http://duckgres.invalid", DUCKGRES_INTERNAL_SECRET="s")
def test_delete_team_hits_org_team_route(mock_internal: MagicMock, _mock_enabled: MagicMock) -> None:
    org_id = uuid4()
    mock_internal.request.return_value = MagicMock(status_code=200, **{"json.return_value": {}})

    resp = managed_warehouse.delete_team(org_id, 42)

    assert resp.status_code == 200
    method, url = mock_internal.request.call_args.args
    assert method == "DELETE"
    assert url == f"http://duckgres.invalid/api/v1/orgs/{org_id}/teams/42"


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.list_teams")
def test_team_onboarding_state_for_duckgres_team(mock_list: MagicMock) -> None:
    mock_list.return_value = Response([{"team_id": 42, "schema_name": "mine"}], status=200)

    state = managed_warehouse.team_onboarding_state(uuid4(), 42)

    assert state == {"team_onboarded": True, "schema_name": "mine"}


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.list_teams")
def test_team_onboarding_state_for_unonboarded_team(mock_list: MagicMock) -> None:
    # Warehouse exists but this team has no row — the onboarding screen case.
    mock_list.return_value = Response([{"team_id": 43, "schema_name": "other"}], status=200)

    state = managed_warehouse.team_onboarding_state(uuid4(), 42)

    assert state == {"team_onboarded": False, "schema_name": None}


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.list_teams")
def test_team_onboarding_state_degrades_when_control_plane_unreachable(mock_list: MagicMock) -> None:
    # The status read must never fail on the control plane: an unreachable CP degrades to
    # the not-onboarded shape.
    mock_list.return_value = Response({"error": "unreachable"}, status=502)

    state = managed_warehouse.team_onboarding_state(uuid4(), 42)

    assert state == {"team_onboarded": False, "schema_name": None}


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.list_teams")
def test_check_schema_name_availability(mock_list: MagicMock) -> None:
    mock_list.return_value = Response([{"team_id": 999, "schema_name": "in_duckgres"}], status=200)

    for name, available in (("in_duckgres", False), ("fresh_name", True)):
        resp = managed_warehouse.check_schema_name(uuid4(), name)
        assert resp.status_code == 200, name
        assert resp.data == {"name": name, "available": available}


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.list_teams")
def test_check_schema_name_rejects_invalid_name(mock_list: MagicMock) -> None:
    resp = managed_warehouse.check_schema_name(uuid4(), "Bad Name")

    assert resp.status_code == 400
    mock_list.assert_not_called()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.delete_team")
def test_block_team_deletion_skips_orgs_without_warehouse(mock_delete: MagicMock) -> None:
    # Teams with no warehouse involvement must never trigger a control-plane call.
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)

    assert managed_warehouse.block_team_deletion(team.id, org.id) is None
    mock_delete.assert_not_called()


@parameterized.expand(
    [
        ("deleted", 200, None),
        ("not_in_duckgres", 404, None),
    ]
)
@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.delete_team")
def test_block_team_deletion_proceeds_when_duckgres_row_gone(
    _name: str, cp_status: int, expected: None, mock_delete: MagicMock
) -> None:
    org, team, _ = _provisioned_org()
    mock_delete.return_value = Response({}, status=cp_status)

    assert managed_warehouse.block_team_deletion(team.id, org.id) is expected
    mock_delete.assert_called_once_with(org.id, team.id, require_enabled=False)


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.delete_team")
def test_block_team_deletion_blocks_last_warehouse_team(mock_delete: MagicMock) -> None:
    # duckgres 409s on the org's last team: the Django deletion must be blocked with guidance
    # to deprovision the warehouse (or delete the organization) instead.
    org, team, _ = _provisioned_org()
    mock_delete.return_value = Response({"error": "last team"}, status=409)

    reason = managed_warehouse.block_team_deletion(team.id, org.id)

    assert reason is not None
    assert "deprovision" in reason.lower()


@parameterized.expand(
    [
        # CP row lists the team → onboarded, block with a retry error.
        ("onboarded", "row"),
        # CP row list unreachable → fail closed: a possibly-onboarded team must not be
        # silently orphaned in duckgres.
        ("membership_unknown", None),
    ]
)
@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.delete_team")
def test_block_team_deletion_blocks_when_delete_fails_and_membership_possible(
    _name: str, cp_rows_kind: str | None, mock_delete: MagicMock
) -> None:
    org, team, _ = _provisioned_org()
    mock_delete.return_value = Response({"error": "unreachable"}, status=502)
    rows = [{"org_id": str(org.id), "team_id": team.id, "schema_name": "mine"}] if cp_rows_kind else None

    with patch("posthog.ducklake.cp_teams._fetch_org_rows", return_value=rows):
        reason = managed_warehouse.block_team_deletion(team.id, org.id)

    assert reason is not None
    assert "try again" in reason.lower()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.delete_team")
def test_block_team_deletion_lets_unonboarded_team_through_on_control_plane_error(mock_delete: MagicMock) -> None:
    # The org has a warehouse but this team has no membership row: a control-plane
    # outage must not brick its deletion.
    org, team, _ = _provisioned_org()
    mock_delete.return_value = Response({"error": "unreachable"}, status=502)

    with patch("posthog.ducklake.cp_teams._fetch_org_rows", return_value=[]):
        assert managed_warehouse.block_team_deletion(team.id, org.id) is None


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.deprovision")
def test_deprovision_for_org_deletion_skips_orgs_without_warehouse(mock_deprovision: MagicMock) -> None:
    # Orgs with no managed warehouse must never trigger a control-plane call.
    org = Organization.objects.create(name="Org")

    managed_warehouse.deprovision_for_org_deletion(org.id)

    mock_deprovision.assert_not_called()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.deprovision")
def test_deprovision_for_org_deletion_deprovisions_the_orgs_warehouse(mock_deprovision: MagicMock) -> None:
    # The flag is bypassed: org deletion must not depend on flag evaluation on the Temporal worker.
    org, _team, _server = _provisioned_org()
    mock_deprovision.return_value = Response({"status": "deprovisioning started", "org": str(org.id)}, status=202)

    managed_warehouse.deprovision_for_org_deletion(org.id)

    mock_deprovision.assert_called_once_with(org.id, require_enabled=False)


@parameterized.expand(
    [
        ("unknown_to_duckgres", 404),
        ("teardown_already_started", 409),
        ("provisioning_api_not_configured", 501),
    ]
)
@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.deprovision")
def test_deprovision_for_org_deletion_treats_converged_states_as_done(
    _name: str, cp_status: int, mock_deprovision: MagicMock
) -> None:
    # 404 (no warehouse in duckgres), 409 (teardown already started/finished — deprovision is not
    # re-POSTable), and 501 (no provisioning API configured) all mean there is nothing to start.
    org, _team, _server = _provisioned_org()
    mock_deprovision.return_value = Response({"error": "nope"}, status=cp_status)

    managed_warehouse.deprovision_for_org_deletion(org.id)  # must not raise

    mock_deprovision.assert_called_once_with(org.id, require_enabled=False)


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_provision_rejected_for_org_pending_deletion(mock_request: MagicMock) -> None:
    # The deletion workflow's deprovision step runs once, early: a warehouse provisioned for a
    # pending-deletion org afterwards would be cascade-deleted without ever being deprovisioned,
    # so the control plane must never be reached.
    org = Organization.objects.create(name="Org", is_pending_deletion=True)
    team = Team.objects.create(organization=org, name="Env")

    resp = managed_warehouse.provision(org.id, "my-warehouse", team.id, "myschema", require_enabled=False)

    assert resp.status_code == 409
    assert "pending deletion" in resp.data["error"]
    mock_request.assert_not_called()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.create_team")
def test_onboard_team_rejected_for_org_pending_deletion(mock_create_team: MagicMock) -> None:
    org = Organization.objects.create(name="Org", is_pending_deletion=True)
    team = Team.objects.create(organization=org, name="Env")

    resp = managed_warehouse.onboard_team(org.id, team.id, "myschema", require_enabled=False)

    assert resp.status_code == 409
    assert "pending deletion" in resp.data["error"]
    mock_create_team.assert_not_called()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.deprovision")
def test_deprovision_for_org_deletion_raises_on_control_plane_error(mock_deprovision: MagicMock) -> None:
    # A transient failure must raise so the Temporal activity retries instead of silently
    # orphaning the warehouse.
    org, _team, _server = _provisioned_org()
    mock_deprovision.return_value = Response({"error": "unreachable"}, status=502)

    with pytest.raises(RuntimeError, match="deprovision failed"):
        managed_warehouse.deprovision_for_org_deletion(org.id)


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.internal_requests")
@override_settings(DUCKGRES_API_URL="http://duckgres.invalid", DUCKGRES_INTERNAL_SECRET="s")
def test_update_team_puts_only_passed_fields_to_org_team_route(mock_internal: MagicMock) -> None:
    # The earliest-event-date mirror uses the admin PUT: only the passed fields may appear
    # in the body, so the presence-aware CP update can't clobber schema/table names.
    org_id = uuid4()
    mock_internal.request.return_value = MagicMock(status_code=200, **{"json.return_value": {}})

    resp = managed_warehouse.update_team(org_id, 42, require_enabled=False, earliest_event_date="2020-06-15")

    assert resp.status_code == 200
    method, url = mock_internal.request.call_args.args
    assert method == "PUT"
    assert url == f"http://duckgres.invalid/api/v1/orgs/{org_id}/teams/42"
    assert mock_internal.request.call_args.kwargs["json"] == {"earliest_event_date": "2020-06-15"}
