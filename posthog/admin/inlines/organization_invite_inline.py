from django_admin_inline_paginator.admin import TabularInlinePaginated

from posthog.models.organization_invite import OrganizationInvite


class OrganizationInviteInline(TabularInlinePaginated):
    extra = 0
    model = OrganizationInvite
    per_page = 20
    pagination_key = "page-invite"
    readonly_fields = ("created_at", "updated_at", "emailing_attempt_made", "private_project_access")
    autocomplete_fields = ("organization",)

    can_delete = False
    show_change_link = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
