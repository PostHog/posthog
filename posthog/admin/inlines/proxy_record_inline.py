from django.http import HttpRequest

from django_admin_inline_paginator.admin import TabularInlinePaginated

from posthog.models.organization import Organization
from posthog.models.proxy_record import ProxyRecord


class ProxyRecordInline(TabularInlinePaginated):
    extra = 0
    model = ProxyRecord
    per_page = 20
    pagination_key = "page-proxy-record"
    show_change_link = True
    verbose_name = "reverse proxy"
    verbose_name_plural = "Reverse proxies"

    fields = (
        "domain",
        "status",
        "target_cname",
        "message",
        "created_at",
    )

    readonly_fields = fields

    ordering = ("-created_at",)

    def has_add_permission(self, request: HttpRequest, obj: Organization | None = None) -> bool:
        # Proxy records are created via the app, not the admin
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Organization | None = None) -> bool:
        return False
