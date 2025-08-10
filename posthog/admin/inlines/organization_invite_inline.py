from django.contrib import admin

from posthog.models.organization_invite import OrganizationInvite


class OrganizationInviteInline(admin.TabularInline):
    extra = 0
    model = OrganizationInvite
    readonly_fields = ("created_at", "updated_at", "emailing_attempt_made", "private_project_access")
    autocomplete_fields = ("organization",)

    can_delete = False
    show_change_link = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
