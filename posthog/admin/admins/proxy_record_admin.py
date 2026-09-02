from django.contrib import admin
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from posthog.models import ProxyRecord


@admin.register(ProxyRecord)
class ProxyRecordAdmin(admin.ModelAdmin):
    list_display = ("domain", "organization_link", "status", "target_cname", "created_at")
    list_filter = ("status",)
    search_fields = ("domain", "organization__name")
    list_select_related = ("organization", "created_by")
    readonly_fields = (
        "id",
        "domain",
        "organization_link",
        "status",
        "target_cname",
        "message",
        "created_by_link",
        "created_at",
        "updated_at",
    )
    fields = (
        "id",
        "domain",
        "organization_link",
        "status",
        "target_cname",
        "message",
        "created_by_link",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: ProxyRecord | None = None) -> bool:
        return False

    @admin.display(description="Organization", ordering="organization__name")
    def organization_link(self, obj: ProxyRecord) -> str:
        url = reverse("admin:posthog_organization_change", args=[obj.organization_id])
        return format_html('<a href="{}">{}</a>', url, obj.organization.name)

    @admin.display(description="Created by", ordering="created_by__email")
    def created_by_link(self, obj: ProxyRecord) -> str:
        if not obj.created_by:
            return "-"
        url = reverse("admin:posthog_user_change", args=[obj.created_by_id])
        return format_html('<a href="{}">{}</a>', url, obj.created_by.email)
