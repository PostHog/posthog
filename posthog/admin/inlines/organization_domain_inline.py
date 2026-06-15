from django_admin_inline_paginator.admin import TabularInlinePaginated

from posthog.models.organization_domain import OrganizationDomain


class OrganizationDomainInline(TabularInlinePaginated):
    extra = 0
    model = OrganizationDomain
    per_page = 20
    pagination_key = "page-domain"
    show_change_link = True

    fields = (
        "domain",
        "verified_at",
        "jit_provisioning_enabled",
        "sso_enforcement",
        "verification_challenge",
    )

    readonly_fields = ("id", "domain", "verification_challenge", "verified_at")

    ordering = ("domain",)

    def has_add_permission(self, request, obj=None):
        # Prevent adding Domains through the admin (they should be created via API)
        return False
