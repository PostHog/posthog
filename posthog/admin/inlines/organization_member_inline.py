from django.contrib import admin

from posthog.models.organization import OrganizationMembership


class OrganizationMemberInline(admin.TabularInline):
    extra = 0
    model = OrganizationMembership
    readonly_fields = ("user", "joined_at", "updated_at")
    autocomplete_fields = ("user", "organization")
