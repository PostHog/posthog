from django_admin_inline_paginator.admin import TabularInlinePaginated

from posthog.models.organization import OrganizationMembership


class OrganizationMemberInline(TabularInlinePaginated):
    extra = 0
    model = OrganizationMembership
    per_page = 20
    pagination_key = "page-member"
    show_change_link = True
    readonly_fields = ("user", "joined_at", "updated_at")
    autocomplete_fields = ("user", "organization")
    ordering = ("-level",)  # Order by level descending (Owner -> Admin -> Member)
