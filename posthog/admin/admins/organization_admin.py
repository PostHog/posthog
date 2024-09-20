from django.conf import settings
from django.contrib import admin
from django.utils.html import format_html
from posthog.admin.inlines.organization_member_inline import OrganizationMemberInline
from posthog.admin.inlines.project_inline import ProjectInline
from posthog.admin.inlines.team_inline import TeamInline
from posthog.admin.paginators.no_count_paginator import NoCountPaginator

from posthog.models.organization import Organization


class OrganizationAdmin(admin.ModelAdmin):
    show_full_result_count = False  # prevent count() queries to show the no of filtered results
    paginator = NoCountPaginator  # prevent count() queries and return a fix page count instead
    fields = [
        "id",
        "name",
        "created_at",
        "updated_at",
        "plugins_access_level",
        "billing_link",
        "usage_posthog",
        "usage",
        "customer_trust_scores",
        "is_hipaa",
    ]
    inlines = [ProjectInline, TeamInline, OrganizationMemberInline]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "billing_link",
        "usage_posthog",
        "usage",
        "customer_trust_scores",
    ]
    search_fields = ("name", "members__email", "team__api_token")
    list_display = (
        "id",
        "name",
        "created_at",
        "plugins_access_level",
        "members_count",
        "first_member",
        "billing_link",
    )
    list_display_links = (
        "id",
        "name",
    )

    def members_count(self, organization: Organization):
        return organization.members.count()

    def first_member(self, organization: Organization):
        user = organization.members.order_by("id").first()
        return (
            format_html(f'<a href="/admin/posthog/user/{user.pk}/change/">{user.email}</a>')
            if user is not None
            else "None"
        )

    def billing_link(self, organization: Organization) -> str:
        url = f"{settings.BILLING_SERVICE_URL}/admin/billing/customer/?q={organization.pk}"
        return format_html(f'<a href="{url}">Billing →</a>')

    def usage_posthog(self, organization: Organization):
        return format_html(
            '<a target="_blank" href="/insights/new?insight=TRENDS&interval=day&display=ActionsLineGraph&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%2C%22math%22%3A%22dau%22%7D%5D&properties=%5B%7B%22key%22%3A%22organization_id%22%2C%22value%22%3A%22{}%22%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22person%22%7D%5D&actions=%5B%5D&new_entity=%5B%5D">See usage on PostHog →</a>',
            organization.id,
        )
