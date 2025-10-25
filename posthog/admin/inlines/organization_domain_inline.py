from posthog.admin.inlines.tabular_inline_paginated import TabularInlinePaginated
from posthog.models import OrganizationDomain


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

    readonly_fields = ("verification_challenge", "verified_at")

    ordering = ("domain",)
