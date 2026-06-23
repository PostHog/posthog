from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import Http404, HttpRequest
from django.test import RequestFactory
from django.urls import reverse

from rest_framework.response import Response

from posthog.admin.admins.duckgres_server_admin import DuckgresServerAdmin
from posthog.models import DuckgresServer, Organization, Team

MW = "products.data_warehouse.backend.api.managed_warehouse"


def _attach_messages(request) -> None:
    request.session = {}
    request._messages = FallbackStorage(request)


def _messages(request) -> list[str]:
    return [str(m) for m in get_messages(request)]


class TestDuckgresServerAdminProvision(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.factory = RequestFactory()
        self.admin = DuckgresServerAdmin(DuckgresServer, AdminSite())

    def _post(self, url: str, data: dict) -> HttpRequest:
        request = self.factory.post(url, data)
        request.user = self.user
        _attach_messages(request)
        return request

    def _get(self, url: str) -> HttpRequest:
        request = self.factory.get(url)
        request.user = self.user
        _attach_messages(request)
        return request

    def _server(self) -> DuckgresServer:
        return DuckgresServer.objects.create(
            organization=self.organization, host="h", port=5432, database="ducklake", username="root", password="x"
        )

    def test_provision_post_calls_managed_warehouse_bypassing_flag(self) -> None:
        request = self._post(
            "/admin/posthog/duckgresserver/provision/",
            {
                "organization_id": str(self.organization.id),
                "team_id": str(self.team.id),
                "database_name": "my-warehouse",
                "table_name": "prod_events",
            },
        )
        with patch(f"{MW}.provision", return_value=Response({"status": "ok"}, status=202)) as mock_provision:
            self.admin.provision_view(request)

        mock_provision.assert_called_once_with(
            self.organization.id, "my-warehouse", self.team.id, "prod_events", require_enabled=False
        )
        assert any("Provisioned managed warehouse" in m for m in _messages(request))

    def test_provision_rejects_team_org_mismatch(self) -> None:
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org)
        request = self._post(
            "/admin/posthog/duckgresserver/provision/",
            {
                "organization_id": str(self.organization.id),
                "team_id": str(other_team.id),
                "database_name": "my-warehouse",
                "table_name": "prod_events",
            },
        )
        with patch(f"{MW}.provision") as mock_provision:
            self.admin.provision_view(request)

        mock_provision.assert_not_called()
        assert any("does not belong to organization" in m for m in _messages(request))

    def test_provision_surfaces_helper_error(self) -> None:
        request = self._post(
            "/admin/posthog/duckgresserver/provision/",
            {
                "organization_id": str(self.organization.id),
                "team_id": str(self.team.id),
                "database_name": "my-warehouse",
                "table_name": "prod_events",
            },
        )
        with patch(f"{MW}.provision", return_value=Response({"error": "boom"}, status=400)):
            self.admin.provision_view(request)

        assert any("Failed (status 400): boom" in m for m in _messages(request))

    def test_enable_backfill_post_calls_helper_bypassing_flag(self) -> None:
        server = self._server()
        request = self._post(
            f"/admin/posthog/duckgresserver/{server.pk}/enable-backfill/",
            {"team_id": str(self.team.id), "table_name": "env_b"},
        )
        with patch(
            f"{MW}.enable_backfill", return_value=Response({"enabled": True, "table_suffix": "env_b"}, status=200)
        ) as mock_enable:
            self.admin.enable_backfill_view(request, str(server.pk))

        mock_enable.assert_called_once_with(self.organization.id, self.team.id, "env_b", require_enabled=False)

    def test_enable_backfill_invalid_server_returns_404(self) -> None:
        request = self._get("/admin/posthog/duckgresserver/999999/enable-backfill/")

        with self.assertRaises(Http404):
            self.admin.enable_backfill_view(request, "999999")

    def test_deprovision_post_calls_helper_bypassing_flag(self) -> None:
        server = self._server()
        request = self._post(f"/admin/posthog/duckgresserver/{server.pk}/deprovision/", {})
        with patch(f"{MW}.deprovision", return_value=Response({"status": "ok"}, status=200)) as mock_deprovision:
            self.admin.deprovision_view(request, str(server.pk))

        mock_deprovision.assert_called_once_with(self.organization.id, require_enabled=False)

    def test_deprovision_invalid_server_returns_404(self) -> None:
        request = self._get("/admin/posthog/duckgresserver/999999/deprovision/")

        with self.assertRaises(Http404):
            self.admin.deprovision_view(request, "999999")

    def test_deprovision_failure_returns_to_change_page_and_logs(self) -> None:
        server = self._server()
        request = self._post(f"/admin/posthog/duckgresserver/{server.pk}/deprovision/", {})

        with (
            patch(f"{MW}.deprovision", return_value=Response({"error": "still running"}, status=409)),
            patch("posthog.admin.admins.duckgres_server_admin.logger.warning") as mock_warning,
        ):
            response = self.admin.deprovision_view(request, str(server.pk))

        assert response["Location"] == reverse("admin:posthog_duckgresserver_change", args=[server.pk])
        assert any("Failed (status 409): still running" in message for message in _messages(request))
        mock_warning.assert_called_once_with(
            "admin_managed_warehouse_action_failed",
            action=f"Deprovisioned managed warehouse for org {self.organization.id}",
            triggered_by=self.user.email,
            status_code=409,
            error="still running",
        )
