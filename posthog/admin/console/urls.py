from uuid import UUID

from django.contrib import admin
from django.http import Http404, HttpRequest, HttpResponse
from django.urls import path, re_path

from posthog.admin.console import views
from posthog.admin.console.moved import MovedToConsole
from posthog.admin.console.records import RECORD_TYPES
from posthog.constants import GROUP_TYPES_LIMIT

from products.legal_documents.backend.facade.api import get_organization_id_for_staff

# Old Django admin URLs of team actions that moved. Staff keep bookmarks to them, query parameters included.
MOVED_TEAM_ACTIONS = {
    "set-api-token": "api-token/set/",
    "add-ai-gateway-credit": "ai-gateway/add-credit/",
    "set-email-sending-tier": "email-sending/set-tier/",
    "rebuild-cache": "#panel-remote-config",
    "enable-ai-gateway": "#panel-ai-gateway",
    "revoke-ai-gateway": "#panel-ai-gateway",
    "clear-ai-gateway-revoke": "#panel-ai-gateway",
    "recompute-email-sending-tier": "#panel-email-sending",
    "suspend-email-sending": "email-sending/suspend/",
    "unsuspend-email-sending": "#panel-email-sending",
    **{f"group-type-mapping/{index}/edit": f"group-types/edit-{index}/" for index in range(GROUP_TYPES_LIMIT)},
}

MOVED_ORGANIZATION_ACTIONS = {
    "limit-product": "#panel-billing",
    "unlimit-product": "#panel-billing",
    "sync-to-billing": "#panel-billing",
    "trigger-deletion": "deletion/delete/",
}

MOVED_DELETION_REQUEST_ACTIONS = {
    "submit": "workflow/submit/",
    "approve": "workflow/approve/",
    "retry": "workflow/retry/",
    "revert-to-draft": "#panel-workflow",
    "verify": "#panel-workflow",
    "fetch-stats": "#panel-stats",
    "preview-stats": "#panel-stats",
}


def legal_document_redirect(request: HttpRequest, pk: UUID, target: str) -> HttpResponse:
    # The old document URLs carry only the document ID, so the organization is looked up to find the panel.
    organization_id = get_organization_id_for_staff(pk)
    if organization_id is None:
        raise Http404("Unknown legal document")
    return MovedToConsole.record_redirect("organizations", target)(request, organization_id)


# Every route sits under /admin/, so AdminOAuth2Middleware adds its Google step-up, and admin_view
# adds the staff check, the login redirect and CSRF protection. The console needs no auth of its own.
urlpatterns = [
    path("admin/console/", admin.site.admin_view(views.console_home), name="admin_console_home"),
    *[
        route
        for record_type in RECORD_TYPES.values()
        for route in (
            path(
                f"admin/console/{record_type.plural}/<{record_type.pk_converter}:pk>/",
                admin.site.admin_view(views.record_detail),
                {"record": record_type.key},
                name=record_type.url_name,
            ),
            path(
                f"admin/console/{record_type.plural}/<{record_type.pk_converter}:pk>/<slug:panel_key>/<slug:operation_key>/",
                admin.site.admin_view(views.run_operation),
                {"record": record_type.key},
                name=record_type.operation_url_name,
            ),
        )
    ],
    path(
        "admin/console/tools/<slug:tool_key>/",
        admin.site.admin_view(views.tool_page),
        name="admin_console_tool",
    ),
    path(
        "admin/console/tools/<slug:tool_key>/live/<slug:live_key>/",
        admin.site.admin_view(views.tool_live),
        name="admin_console_tool_live",
    ),
    path(
        "admin/console/tools/<slug:tool_key>/<slug:operation_key>/",
        admin.site.admin_view(views.run_tool_operation),
        name="admin_console_tool_operation",
    ),
    *[
        path(
            f"admin/posthog/team/<int:pk>/{old}/",
            admin.site.admin_view(MovedToConsole.record_redirect("teams", target)),
        )
        for old, target in MOVED_TEAM_ACTIONS.items()
    ],
    *[
        path(
            f"admin/posthog/organization/<uuid:pk>/{old}/",
            admin.site.admin_view(MovedToConsole.record_redirect("organizations", target)),
        )
        for old, target in MOVED_ORGANIZATION_ACTIONS.items()
    ],
    *[
        path(
            f"admin/posthog/datadeletionrequest/<uuid:pk>/{old}/",
            admin.site.admin_view(MovedToConsole.record_redirect("deletion-requests", target)),
        )
        for old, target in MOVED_DELETION_REQUEST_ACTIONS.items()
    ],
    path(
        "admin/posthog/team/<int:pk>/ai-gateway-wallet/",
        MovedToConsole.page_redirect("The AI gateway wallet", "/admin/console/tools/ai-gateway-wallet/?team={pk}"),
    ),
    path(
        "admin/posthog/datadeletionrequest/add/",
        MovedToConsole.page_redirect(
            "Creating a deletion request", "/admin/console/tools/new-deletion-request/create/"
        ),
    ),
    path(
        "admin/posthog/team/<int:pk>/view-cache/",
        MovedToConsole.page_redirect("The cached config view", "/admin/console/tools/remote-config-cache/?team={pk}"),
    ),
    path(
        "admin/posthog/organization/bulk-deactivate/",
        MovedToConsole.page_redirect("Bulk deactivation", "/admin/console/tools/bulk-deactivate-organizations/"),
    ),
    path(
        "admin/posthog/organization/<uuid:pk>/model-counts/",
        MovedToConsole.page_redirect("Child model counts", "/admin/console/tools/organization-data/?organization={pk}"),
    ),
    path(
        "admin/posthog/organization/send-ai-observability-usage-report/",
        MovedToConsole.page_redirect(
            "Sending AI observability usage reports", "/admin/console/tools/ai-observability/"
        ),
    ),
    path(
        "admin/posthog/organization/ai-observability-dataset-retention/",
        MovedToConsole.page_redirect("AI observability dataset retention", "/admin/console/tools/ai-observability/"),
    ),
    path(
        "admin/legal_documents/legaldocument/<uuid:pk>/refetch-pdf/",
        admin.site.admin_view(legal_document_redirect),
        {"target": "#panel-legal-documents"},
    ),
    # The Delete button of the Django admin change page leads to the console operation, which says what a delete
    # leaves behind: PandaDoc's copy of a signed document, and the AI opt-outs of a BAA.
    path(
        "admin/legal_documents/legaldocument/<uuid:pk>/delete/",
        admin.site.admin_view(legal_document_redirect),
        {"target": "legal-documents/delete/"},
    ),
    path(
        "admin/posthog/organization/send-usage-report/",
        MovedToConsole.page_redirect("Sending usage reports", "/admin/console/tools/usage-reports/"),
    ),
    # APPEND_SLASH is off, so a console URL typed without its trailing slash would fall through to the
    # Django admin catch-all.
    re_path(
        r"^admin/console(?P<rest>(?:/.*[^/])?)$",
        admin.site.admin_view(views.append_slash),
        name="admin_console_append_slash",
    ),
]
