from django_admin_inline_paginator.admin import TabularInlinePaginated

from posthog.models.organization import OrganizationMembership


class OrganizationMemberInline(TabularInlinePaginated):
    extra = 0
    model = OrganizationMembership
    per_page = 20
    pagination_key = "page-member"
    show_change_link = True
    # Keep all user FKs out of Django's default <select> rendering (which performs a full
    # User-table fetch per inline row). We only display invited_by read-only in admin.
    fields = ("organization", "user", "invited_by", "level", "joined_at", "updated_at")
    readonly_fields = ("organization", "user", "invited_by", "joined_at", "updated_at")
    autocomplete_fields = ("organization",)
    ordering = ("-level",)  # Order by level descending (Owner -> Admin -> Member)

    def has_add_permission(self, request, obj=None):
        # user/invited_by are read-only here, so Django strips them from the POST body and a new
        # row would insert with user_id=NULL, violating the non-nullable FK. Members are added
        # through the invite flow, not this inline, so disable adding rows outright.
        return False


class OrganizationMemberForUserInline(OrganizationMemberInline):
    """Variant used under UserAdmin — disambiguates the two FKs from OrganizationMembership
    to User (``user`` vs the newer ``invited_by``)."""

    fk_name = "user"
