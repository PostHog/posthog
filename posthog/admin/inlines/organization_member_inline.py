from django_admin_inline_paginator.admin import TabularInlinePaginated

from posthog.models.organization import OrganizationMembership


class OrganizationMemberInline(TabularInlinePaginated):
    extra = 0
    model = OrganizationMembership
    per_page = 20
    pagination_key = "page-member"
    show_change_link = True
    # `invited_by` is a FK to User. Without it being readonly/raw_id/autocomplete, Django
    # admin renders it with a default <select> whose queryset is User.objects.all() — for
    # every row of the inline — which caused the org admin page to stall or 504 on orgs
    # with many members on instances with a large User table.
    readonly_fields = ("organization", "user", "invited_by", "joined_at", "updated_at")
    autocomplete_fields = ("organization",)
    ordering = ("-level",)  # Order by level descending (Owner -> Admin -> Member)


class OrganizationMemberForUserInline(OrganizationMemberInline):
    """Variant used under UserAdmin — disambiguates the two FKs from OrganizationMembership
    to User (``user`` vs the newer ``invited_by``)."""

    fk_name = "user"
