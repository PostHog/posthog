from uuid import uuid4

import pytest
from unittest.mock import MagicMock, call, patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework.response import Response

from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam
from posthog.models import Organization, Team

from products.data_warehouse.backend.presentation.views import managed_warehouse


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_configure_project_reader_creates_a_missing_team_row_before_rotating_credentials(
    mock_request: MagicMock,
) -> None:
    organization_id = uuid4()
    mock_request.side_effect = [
        Response({"teams": []}, status=200),
        Response({"team_id": 42}, status=200),
        Response({"username": "posthog_team_42", "password": "reader-password"}, status=200),
    ]

    credentials = managed_warehouse.configure_project_reader(
        organization_id=organization_id,
        team_id=42,
        table_suffix="prod",
        password="caller-managed-password-with-32-characters",
    )

    assert credentials == {"username": "posthog_team_42", "password": "reader-password"}
    assert mock_request.call_args_list == [
        call("GET", organization_id, "/teams", require_enabled=False),
        call(
            "POST",
            organization_id,
            "/teams",
            json_body={
                "team_id": 42,
                "schema_name": "team_42",
                "enabled": True,
                "events_table_name": "events_prod",
                "persons_table_name": "persons_prod",
                "schema_data_imports_name": "posthog_data_imports_prod",
            },
            require_enabled=False,
        ),
        call(
            "PUT",
            organization_id,
            "/teams/42/project-reader",
            json_body={"password": "caller-managed-password-with-32-characters"},
            require_enabled=False,
        ),
    ]


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_configure_project_reader_never_rewrites_an_existing_team_row(mock_request: MagicMock) -> None:
    # The Duckgres org-team row also drives external-writer discovery (viaduck/millpond), and rows
    # can be hand-set (break-glass edits, legacy layouts like the dogfood devex/team-2 rows).
    # Credential setup must therefore never POST over an existing row.
    organization_id = uuid4()
    mock_request.side_effect = [
        Response(
            {"teams": [{"team_id": 42, "schema_name": "devex", "enabled": True, "events_table_name": "events"}]},
            status=200,
        ),
        Response({"username": "posthog_team_42", "password": "reader-password"}, status=200),
    ]

    credentials = managed_warehouse.configure_project_reader(
        organization_id=organization_id,
        team_id=42,
        table_suffix="prod",
        password="caller-managed-password-with-32-characters",
    )

    assert credentials == {"username": "posthog_team_42", "password": "reader-password"}
    assert mock_request.call_args_list == [
        call("GET", organization_id, "/teams", require_enabled=False),
        call(
            "PUT",
            organization_id,
            "/teams/42/project-reader",
            json_body={"password": "caller-managed-password-with-32-characters"},
            require_enabled=False,
        ),
    ]


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_configure_project_reader_refuses_a_disabled_team_row(mock_request: MagicMock) -> None:
    # `enabled` is an operator-facing serving hold; credential setup must not silently lift it.
    mock_request.return_value = Response(
        {"teams": [{"team_id": 42, "schema_name": "team_42", "enabled": False}]}, status=200
    )

    with pytest.raises(RuntimeError, match="disabled"):
        managed_warehouse.configure_project_reader(
            organization_id=uuid4(),
            team_id=42,
            table_suffix="prod",
            password="caller-managed-password-with-32-characters",
        )

    assert len(mock_request.call_args_list) == 1


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_project_reader_namespaces_mirror_the_duckgres_team_row(mock_request: MagicMock) -> None:
    # Must match the Duckgres policy derivation: a non-NULL legacy override always grants
    # posthog.<name> — including overrides that spell the derived default (team 2's
    # events_table_name="events" -> posthog.events); NULL overrides grant nothing extra.
    mock_request.return_value = Response(
        {
            "teams": [
                {
                    "team_id": 2,
                    "schema_name": "team_2",
                    "enabled": True,
                    "events_table_name": "events",
                    "persons_table_name": "persons",
                    "schema_data_imports_name": "posthog_data_imports_team_2",
                }
            ]
        },
        status=200,
    )

    namespaces = managed_warehouse.project_reader_namespaces(organization_id=uuid4(), team_id=2)

    assert namespaces == (
        {"team_2", "posthog_data_imports_team_2", "shadow_2_models"},
        {("posthog", "events"), ("posthog", "persons")},
    )


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_project_reader_namespaces_derive_imports_and_skip_absent_overrides(mock_request: MagicMock) -> None:
    mock_request.return_value = Response(
        {"teams": [{"team_id": 7, "schema_name": "team_7", "enabled": True}]}, status=200
    )

    namespaces = managed_warehouse.project_reader_namespaces(organization_id=uuid4(), team_id=7)

    assert namespaces == ({"team_7", "team_7_data_imports", "shadow_7_models"}, set())


@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_project_reader_namespaces_fail_closed_without_an_enabled_row(mock_request: MagicMock) -> None:
    mock_request.return_value = Response(
        {"teams": [{"team_id": 7, "schema_name": "team_7", "enabled": False}]}, status=200
    )

    assert managed_warehouse.project_reader_namespaces(organization_id=uuid4(), team_id=7) is None
    assert managed_warehouse.project_reader_namespaces(organization_id=uuid4(), team_id=8) is None


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
def test_onboard_team_dual_writes_duckgres_and_django(mock_request: MagicMock, _mock_enabled: MagicMock) -> None:
    org, team, server = _provisioned_org()
    mock_request.return_value = Response({"team_id": team.id, "schema_name": "my_events"}, status=200)

    resp = managed_warehouse.onboard_team(org.id, team.id, "my_events")

    assert resp.status_code == 200
    assert resp.data == {"onboarded": True, "schema_name": "my_events"}

    # duckgres team row created via the org-teams upsert WITH the legacy table names the
    # duckling DAG actually writes today (posthog.events_<suffix> + posthog_data_imports_<suffix>).
    # A row without them grants the project reader only nonexistent derived schemas — the
    # empty-SQL-editor-sidebar bug the EU placeholder rows hit.
    method, org_id, path = mock_request.call_args_list[0].args
    assert (method, org_id, path) == ("POST", org.id, "/teams")
    json_body = mock_request.call_args_list[0].kwargs["json_body"]
    assert json_body == {
        "team_id": team.id,
        "schema_name": "my_events",
        "events_table_name": "events_my_events",
        "persons_table_name": "persons_my_events",
        "schema_data_imports_name": "posthog_data_imports_my_events",
    }

    link = DuckgresServerTeam.objects.get(server=server, team_id=team.id)
    assert link.backfill_enabled is True
    assert link.table_suffix == "my_events"


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_onboard_team_surfaces_duckgres_schema_conflict(mock_request: MagicMock, _mock_enabled: MagicMock) -> None:
    # duckgres owns cross-team schema uniqueness (it also knows grandfathered schemas Django
    # doesn't) — its 409 must reach the caller as a clear conflict, with no Django row written.
    org, team, _ = _provisioned_org()
    mock_request.return_value = Response({"error": "schema already in use"}, status=409)

    resp = managed_warehouse.onboard_team(org.id, team.id, "taken")

    assert resp.status_code == 409
    assert "taken" in resp.data["error"]
    assert not DuckgresServerTeam.objects.filter(team_id=team.id).exists()


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
    assert not DuckgresServerTeam.objects.filter(team_id=team.id).exists()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_onboard_team_rejects_duplicate_suffix_before_control_plane(
    mock_request: MagicMock, _mock_enabled: MagicMock
) -> None:
    # The Django guard must run before the duckgres upsert: the upsert overwrites an existing
    # row's schema, so a rejected name must never reach the control plane.
    org, team_a, server = _provisioned_org()
    team_b = Team.objects.create(organization=org, name="Env B")
    DuckgresServerTeam.objects.create(server=server, team=team_a, table_suffix="shared")

    resp = managed_warehouse.onboard_team(org.id, team_b.id, "shared")

    assert resp.status_code == 400
    mock_request.assert_not_called()
    assert not DuckgresServerTeam.objects.filter(team_id=team_b.id).exists()


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
    assert not DuckgresServerTeam.objects.filter(team_id=team.id).exists()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_onboard_team_same_name_is_idempotent(mock_request: MagicMock, _mock_enabled: MagicMock) -> None:
    org, team, _ = _provisioned_org()
    mock_request.return_value = Response({"team_id": team.id, "schema_name": "first"}, status=200)

    managed_warehouse.onboard_team(org.id, team.id, "first")
    resp = managed_warehouse.onboard_team(org.id, team.id, "first")

    assert resp.status_code == 200
    assert DuckgresServerTeam.objects.filter(team_id=team.id).count() == 1
    assert DuckgresServerTeam.objects.get(team_id=team.id).table_suffix == "first"


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_onboard_team_refuses_to_change_an_existing_suffix(mock_request: MagicMock, _mock_enabled: MagicMock) -> None:
    org, team, _ = _provisioned_org()
    mock_request.return_value = Response({"team_id": team.id, "schema_name": "first"}, status=200)
    managed_warehouse.onboard_team(org.id, team.id, "first")
    mock_request.reset_mock()

    resp = managed_warehouse.onboard_team(org.id, team.id, "second")

    # Changing a set suffix would split the team's data across two tables — rejected before
    # the control plane, so the duckgres row keeps its schema too.
    assert resp.status_code == 400
    mock_request.assert_not_called()
    assert DuckgresServerTeam.objects.get(team_id=team.id).table_suffix == "first"


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
def test_onboard_team_refuses_to_set_a_suffix_on_a_legacy_shared_team(
    mock_request: MagicMock, _mock_enabled: MagicMock
) -> None:
    org, team, server = _provisioned_org()
    # A legacy team already backfilling to the shared tables (NULL suffix), e.g. backfilled by migration.
    DuckgresServerTeam.objects.create(server=server, team=team, backfill_enabled=True, table_suffix=None)

    resp = managed_warehouse.onboard_team(org.id, team.id, "new_name")

    assert resp.status_code == 400
    mock_request.assert_not_called()
    assert DuckgresServerTeam.objects.get(team_id=team.id).table_suffix is None


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


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.create_team")
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.list_teams")
def test_team_onboarding_state_for_duckgres_team(mock_list: MagicMock, mock_create: MagicMock) -> None:
    # Branch b: the duckgres row exists — onboarded, no grandfather push.
    org, team, server = _provisioned_org()
    DuckgresServerTeam.objects.create(server=server, team=team, table_suffix="mine")
    mock_list.return_value = Response([{"team_id": team.id, "schema_name": "mine"}], status=200)

    state = managed_warehouse.team_onboarding_state(org.id, team.id)

    assert state == {"team_onboarded": True, "schema_name": "mine"}
    mock_create.assert_not_called()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.create_team")
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.list_teams")
def test_team_onboarding_state_for_unonboarded_team(mock_list: MagicMock, mock_create: MagicMock) -> None:
    # Branch c: warehouse exists but this team has no row anywhere — the onboarding screen case.
    org, team, _ = _provisioned_org()
    mock_list.return_value = Response([{"team_id": team.id + 1, "schema_name": "other"}], status=200)

    state = managed_warehouse.team_onboarding_state(org.id, team.id)

    assert state == {"team_onboarded": False, "schema_name": None}
    mock_create.assert_not_called()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.list_teams")
def test_team_onboarding_state_heals_missing_django_row(mock_list: MagicMock) -> None:
    # Reverse heal: a dual-write that lost its Django half (provision registered the team with
    # duckgres but enable_team_backfill failed) is repaired on the next status read, so Dagster
    # picks the team up instead of it reporting onboarded forever with no backfill.
    org, team, _ = _provisioned_org()
    mock_list.return_value = Response([{"team_id": team.id, "schema_name": "healed_env"}], status=200)

    state = managed_warehouse.team_onboarding_state(org.id, team.id)

    assert state == {"team_onboarded": True, "schema_name": "healed_env"}
    row = DuckgresServerTeam.objects.get(team=team)
    assert row.table_suffix == "healed_env"


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.list_teams")
def test_team_onboarding_state_refuses_to_heal_legacy_named_row(mock_list: MagicMock) -> None:
    # A duckgres row with explicit legacy table names came from the grandfather push (which only
    # runs off an existing Django row) — a missing Django row there is unexpected, so the heal
    # must not guess a suffix that would rename the team's tables.
    org, team, _ = _provisioned_org()
    mock_list.return_value = Response(
        [{"team_id": team.id, "schema_name": "team_x", "events_table_name": "events"}], status=200
    )

    state = managed_warehouse.team_onboarding_state(org.id, team.id)

    assert state == {"team_onboarded": True, "schema_name": "team_x"}
    assert not DuckgresServerTeam.objects.filter(team=team).exists()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.list_teams")
def test_team_onboarding_state_survives_failed_heal(mock_list: MagicMock) -> None:
    # A heal that loses to a suffix collision is logged, never failing the status read.
    org, team, server = _provisioned_org()
    other_team = Team.objects.create(organization=org, name="other")
    DuckgresServerTeam.objects.create(server=server, team=other_team, table_suffix="taken_env")
    mock_list.return_value = Response([{"team_id": team.id, "schema_name": "taken_env"}], status=200)

    state = managed_warehouse.team_onboarding_state(org.id, team.id)

    assert state == {"team_onboarded": True, "schema_name": "taken_env"}
    assert not DuckgresServerTeam.objects.filter(team=team).exists()


@parameterized.expand(
    [
        # suffix set: schema is the suffix, explicit suffixed legacy names
        (
            "with_suffix",
            "prod_env",
            {
                "schema_name": "prod_env",
                "events_table_name": "events_prod_env",
                "persons_table_name": "persons_prod_env",
                "schema_data_imports_name": "posthog_data_imports_prod_env",
            },
        ),
        # NULL suffix: legacy shared tables and the team-id data-imports schema
        (
            "without_suffix",
            None,
            {
                "schema_name": None,  # filled per-team below
                "events_table_name": "events",
                "persons_table_name": "persons",
                "schema_data_imports_name": None,  # filled per-team below
            },
        ),
    ]
)
@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.list_teams")
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.internal_requests")
@override_settings(DUCKGRES_API_URL="http://duckgres.invalid", DUCKGRES_INTERNAL_SECRET="s")
def test_team_onboarding_state_lazily_grandfathers_django_only_team(
    _name: str,
    table_suffix: str | None,
    expected: dict,
    mock_internal: MagicMock,
    mock_list: MagicMock,
) -> None:
    # A team onboarded before the control plane tracked teams (Django row only) is pushed to
    # duckgres during the status read, pinning its explicit legacy table names.
    org, team, server = _provisioned_org()
    DuckgresServerTeam.objects.create(server=server, team=team, table_suffix=table_suffix)
    mock_list.return_value = Response([], status=200)
    mock_internal.request.return_value = MagicMock(status_code=200, **{"json.return_value": {}})

    expected = {
        **expected,
        "schema_name": expected["schema_name"] or f"team_{team.id}",
        "schema_data_imports_name": expected["schema_data_imports_name"] or f"posthog_data_imports_team_{team.id}",
    }

    state = managed_warehouse.team_onboarding_state(org.id, team.id)

    assert state == {"team_onboarded": True, "schema_name": expected["schema_name"]}
    assert mock_internal.request.call_args.kwargs["json"] == {"team_id": team.id, **expected}


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.create_team")
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.list_teams")
def test_team_onboarding_state_survives_control_plane_failure(mock_list: MagicMock, mock_create: MagicMock) -> None:
    # The status read must never fail on the control plane: a Django-onboarded team still
    # reports as onboarded (with its would-be schema) when list-teams errors.
    org, team, server = _provisioned_org()
    DuckgresServerTeam.objects.create(server=server, team=team, table_suffix="mine")
    mock_list.return_value = Response({"error": "unreachable"}, status=502)

    state = managed_warehouse.team_onboarding_state(org.id, team.id)

    assert state == {"team_onboarded": True, "schema_name": "mine"}
    mock_create.assert_not_called()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.create_team")
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.list_teams")
def test_team_onboarding_state_survives_failed_grandfather_push(mock_list: MagicMock, mock_create: MagicMock) -> None:
    # A failed push is logged and retried on the next status read; the team still reports
    # onboarded from its Django row.
    org, team, server = _provisioned_org()
    DuckgresServerTeam.objects.create(server=server, team=team, table_suffix="mine")
    mock_list.return_value = Response([], status=200)
    mock_create.return_value = Response({"error": "boom"}, status=500)

    state = managed_warehouse.team_onboarding_state(org.id, team.id)

    assert state == {"team_onboarded": True, "schema_name": "mine"}


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.list_teams")
def test_check_schema_name_availability(mock_list: MagicMock) -> None:
    # Taken by a duckgres row, taken by a Django-only (not yet grandfathered) suffix, or free.
    org, team, server = _provisioned_org()
    DuckgresServerTeam.objects.create(server=server, team=team, table_suffix="django_only")
    mock_list.return_value = Response([{"team_id": 999, "schema_name": "in_duckgres"}], status=200)

    for name, available in (("in_duckgres", False), ("django_only", False), ("fresh_name", True)):
        resp = managed_warehouse.check_schema_name(org.id, name)
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
    org, team, server = _provisioned_org()
    DuckgresServerTeam.objects.create(server=server, team=team, table_suffix="mine")
    mock_delete.return_value = Response({}, status=cp_status)

    assert managed_warehouse.block_team_deletion(team.id, org.id) is expected
    mock_delete.assert_called_once_with(org.id, team.id, require_enabled=False)


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.delete_team")
def test_block_team_deletion_blocks_last_warehouse_team(mock_delete: MagicMock) -> None:
    # duckgres 409s on the org's last team: the Django deletion must be blocked with guidance
    # to deprovision the warehouse (or delete the organization) instead.
    org, team, server = _provisioned_org()
    DuckgresServerTeam.objects.create(server=server, team=team, table_suffix="mine")
    mock_delete.return_value = Response({"error": "last team"}, status=409)

    reason = managed_warehouse.block_team_deletion(team.id, org.id)

    assert reason is not None
    assert "deprovision" in reason.lower()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.delete_team")
def test_block_team_deletion_blocks_onboarded_team_when_control_plane_unreachable(mock_delete: MagicMock) -> None:
    # An onboarded team must not be silently orphaned in duckgres — block with a retry error.
    org, team, server = _provisioned_org()
    DuckgresServerTeam.objects.create(server=server, team=team, table_suffix="mine")
    mock_delete.return_value = Response({"error": "unreachable"}, status=502)

    reason = managed_warehouse.block_team_deletion(team.id, org.id)

    assert reason is not None
    assert "try again" in reason.lower()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.delete_team")
def test_block_team_deletion_lets_unonboarded_team_through_on_control_plane_error(mock_delete: MagicMock) -> None:
    # The org has a warehouse but this team is not onboarded Django-side: a control-plane
    # outage must not brick its deletion.
    org, team, _ = _provisioned_org()
    mock_delete.return_value = Response({"error": "unreachable"}, status=502)

    assert managed_warehouse.block_team_deletion(team.id, org.id) is None


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


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.is_enabled", return_value=True)
@patch("products.data_warehouse.backend.facade.tasks.sync_team_earliest_event_date")
def test_onboard_team_schedules_earliest_event_date_sync_after_commit(
    mock_task: MagicMock,
    _mock_enabled: MagicMock,
    mock_request: MagicMock,
    django_capture_on_commit_callbacks,
) -> None:
    # The resolve task must only fire once the DuckgresServerTeam row is committed,
    # or it could run against a rolled-back membership row.
    org, team, _ = _provisioned_org()
    mock_request.return_value = Response({"team_id": team.id, "schema_name": "my_events"}, status=200)

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        resp = managed_warehouse.onboard_team(org.id, team.id, "my_events")

    assert resp.status_code == 200
    assert len(callbacks) == 1
    mock_task.delay.assert_called_once_with(team.id)


@pytest.mark.django_db
@override_settings(CLOUD_DEPLOYMENT="US", DUCKGRES_PG_PORT=5432)
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse._request")
@patch("products.data_warehouse.backend.facade.tasks.sync_team_earliest_event_date")
def test_provision_schedules_earliest_event_date_sync_after_commit(
    mock_task: MagicMock,
    mock_request: MagicMock,
    django_capture_on_commit_callbacks,
) -> None:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    mock_request.return_value = Response(
        {"status": "provisioning started", "org": str(org.id), "username": "root", "password": "secret"},
        status=202,
    )

    with django_capture_on_commit_callbacks(execute=True):
        managed_warehouse.provision(org.id, "my-warehouse", team.id, "prod_events")

    mock_task.delay.assert_called_once_with(team.id)
