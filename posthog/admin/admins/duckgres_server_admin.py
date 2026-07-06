from typing import cast

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse

import structlog

from posthog.models import DuckgresServer, Organization, Team, User

logger = structlog.get_logger(__name__)


@admin.register(DuckgresServer)
class DuckgresServerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "organization_id",
        "host",
        "port",
        "flight_port",
        "database",
        "bucket",
        "created_at",
        "updated_at",
    )
    search_fields = ("=organization__id", "host", "bucket")
    # bucket / bucket_region are control-plane-owned: provisioning persists them
    # and status_for() self-heals them on every read, so a manual admin edit
    # would just be overwritten. Show them, but read-only.
    readonly_fields = ("id", "created_at", "updated_at", "bucket", "bucket_region")
    raw_id_fields = ("organization",)

    # Custom templates add the provision / enable-backfill / deprovision buttons.
    change_list_template = "admin/posthog/duckgres_server/change_list.html"
    change_form_template = "admin/posthog/duckgres_server/change_form.html"

    change_fieldsets = (
        (
            None,
            {
                "fields": ("id", "organization"),
            },
        ),
        (
            "Connection",
            {
                "fields": ("host", "port", "flight_port", "database", "username"),
            },
        ),
        (
            "DuckLake catalog connection",
            {
                "fields": ("catalog_host", "catalog_port", "catalog_database", "catalog_username"),
            },
        ),
        (
            "Storage",
            {
                # The duckling's per-org S3 bucket. Control-plane-owned and
                # read-only: provisioning persists it and status_for() self-heals
                # it from the warehouse status, so it's shown for reference but not
                # editable here.
                "fields": ("bucket", "bucket_region"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "fields": ("organization",),
            },
        ),
        (
            "Connection",
            {
                "fields": ("host", "port", "flight_port", "database", "username", "password"),
            },
        ),
        (
            "DuckLake catalog connection",
            {
                "fields": ("catalog_host", "catalog_port", "catalog_database", "catalog_username", "catalog_password"),
            },
        ),
        (
            "Storage",
            {
                "fields": ("bucket", "bucket_region"),
            },
        ),
    )

    def get_urls(self):
        custom_urls = [
            path(
                "provision/",
                self.admin_site.admin_view(self.provision_view),
                name="posthog_duckgresserver_provision",
            ),
            path(
                "<path:object_id>/enable-backfill/",
                self.admin_site.admin_view(self.enable_backfill_view),
                name="posthog_duckgresserver_enable_backfill",
            ),
            path(
                "<path:object_id>/deprovision/",
                self.admin_site.admin_view(self.deprovision_view),
                name="posthog_duckgresserver_deprovision",
            ),
        ]
        return custom_urls + super().get_urls()

    def get_fieldsets(self, request: HttpRequest, obj: DuckgresServer | None = None) -> tuple:
        return self.add_fieldsets if obj is None else self.change_fieldsets

    def provision_view(self, request: HttpRequest) -> HttpResponse:
        """Provision a brand-new managed warehouse for an org + its first team.

        Runs the same path as the in-product provision API: the duckgres control-plane
        /provision call, then the DuckgresServer and DuckgresServerTeam records. The org's
        feature flag is bypassed (require_enabled=False) so ops can provision before the org
        is entitled to the in-product UI.
        """
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])

        if not self.has_add_permission(request):
            raise PermissionDenied

        if request.method == "GET":
            return render(
                request,
                "admin/posthog/duckgres_server/provision_form.html",
                {**self.admin_site.each_context(request), "title": "Provision managed warehouse"},
            )

        organization_id = request.POST.get("organization_id", "").strip()
        team_id = request.POST.get("team_id", "").strip()
        database_name = request.POST.get("database_name", "").strip()
        table_name = request.POST.get("table_name", "").strip()

        team = self._resolve_team(request, organization_id, team_id)
        if team is None:
            return redirect(reverse("admin:posthog_duckgresserver_provision"))

        from products.data_warehouse.backend.presentation.views import managed_warehouse  # noqa: PLC0415

        resp = managed_warehouse.provision(
            team.organization_id, database_name, team.id, table_name, require_enabled=False
        )
        if 200 <= resp.status_code < 300:
            # The control plane returns the root password exactly once, in this
            # response; afterwards it's stored only encrypted and can't be read
            # back. Show it once here. Deliberately NOT routed through the message
            # framework (which persists to the session/cookie store) or the audit
            # log — only the action + actor are logged, never the credential.
            user = cast(User, request.user)
            logger.info(
                "admin_managed_warehouse_action",
                action=f"Provisioned managed warehouse for org {team.organization_id}",
                triggered_by=user.email,
            )
            body = resp.data if isinstance(resp.data, dict) else {}
            return render(
                request,
                "admin/posthog/duckgres_server/provision_result.html",
                {
                    **self.admin_site.each_context(request),
                    "title": "Managed warehouse provisioned",
                    "organization_id": str(team.organization_id),
                    "team_id": team.id,
                    "connection": managed_warehouse._present_connection(
                        {"database": database_name, "username": body.get("username", "root")}
                    ),
                    "password": body.get("password", ""),
                },
            )
        self._report(request, resp, f"Provisioned managed warehouse for org {team.organization_id}")
        return redirect(reverse("admin:posthog_duckgresserver_provision"))

    def enable_backfill_view(self, request: HttpRequest, object_id: str) -> HttpResponse:
        """Add another team to an already-provisioned org's warehouse with its own tables."""
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])

        server = self._get_server_or_404(object_id)
        if not self.has_change_permission(request, server):
            raise PermissionDenied

        if request.method == "GET":
            return render(
                request,
                "admin/posthog/duckgres_server/enable_backfill_form.html",
                {
                    **self.admin_site.each_context(request),
                    "title": "Enable warehouse backfill for a team",
                    "server": server,
                },
            )

        team_id = request.POST.get("team_id", "").strip()
        table_name = request.POST.get("table_name", "").strip()

        team = self._resolve_team(request, str(server.organization_id), team_id)
        if team is None:
            return redirect(reverse("admin:posthog_duckgresserver_enable_backfill", args=[object_id]))

        from products.data_warehouse.backend.presentation.views import managed_warehouse  # noqa: PLC0415

        resp = managed_warehouse.enable_backfill(server.organization_id, team.id, table_name, require_enabled=False)
        self._report(request, resp, f"Enabled warehouse backfill for team {team.id}")
        if 200 <= resp.status_code < 300:
            return redirect(reverse("admin:posthog_duckgresserver_change", args=[object_id]))
        return redirect(reverse("admin:posthog_duckgresserver_enable_backfill", args=[object_id]))

    def deprovision_view(self, request: HttpRequest, object_id: str) -> HttpResponse:
        """Tear down an org's managed warehouse via the control-plane /deprovision call."""
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])

        server = self._get_server_or_404(object_id)
        if not self.has_delete_permission(request, server):
            raise PermissionDenied

        if request.method == "GET":
            return render(
                request,
                "admin/posthog/duckgres_server/deprovision_confirm.html",
                {
                    **self.admin_site.each_context(request),
                    "title": "Deprovision managed warehouse",
                    "server": server,
                },
            )

        from products.data_warehouse.backend.presentation.views import managed_warehouse  # noqa: PLC0415

        resp = managed_warehouse.deprovision(server.organization_id, require_enabled=False)
        self._report(request, resp, f"Deprovisioned managed warehouse for org {server.organization_id}")
        if 200 <= resp.status_code < 300:
            return redirect(reverse("admin:posthog_duckgresserver_changelist"))
        return redirect(reverse("admin:posthog_duckgresserver_change", args=[object_id]))

    def _get_server_or_404(self, object_id: str) -> DuckgresServer:
        try:
            return get_object_or_404(DuckgresServer, pk=object_id)
        except ValidationError as exc:
            raise Http404("No DuckgresServer matches the given query.") from exc

    def _resolve_team(self, request: HttpRequest, organization_id: str, team_id: str) -> Team | None:
        """Look up the team and confirm it belongs to the given org, messaging on failure."""
        if not organization_id or not team_id:
            messages.error(request, "Organization and team are both required.")
            return None
        if not Organization.objects.filter(pk=organization_id).exists():
            messages.error(request, f"No organization with id {organization_id}.")
            return None
        team = Team.objects.filter(pk=team_id).first() if team_id.isdigit() else None
        if team is None:
            messages.error(request, f"No team with id {team_id}.")
            return None
        if str(team.organization_id) != str(organization_id):
            messages.error(request, f"Team {team_id} does not belong to organization {organization_id}.")
            return None
        return team

    def _report(self, request: HttpRequest, resp, success_message: str) -> None:
        """Turn a managed_warehouse Response into an admin flash message + audit log."""
        user = cast(User, request.user)
        if 200 <= resp.status_code < 300:
            logger.info("admin_managed_warehouse_action", action=success_message, triggered_by=user.email)
            messages.success(request, f"{success_message}. (status {resp.status_code})")
            return
        detail = resp.data.get("error") if isinstance(resp.data, dict) else resp.data
        logger.warning(
            "admin_managed_warehouse_action_failed",
            action=success_message,
            triggered_by=user.email,
            status_code=resp.status_code,
            error=detail,
        )
        messages.error(request, f"Failed (status {resp.status_code}): {detail}")
