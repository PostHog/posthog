from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from posthog.models import (
    Action,
    ActionStep,
    Element,
    FeatureFlag,
    Insight,
    InstanceSetting,
    Organization,
    Person,
    Plugin,
    PluginConfig,
    Team,
    User,
)

admin.site.register(Person)
admin.site.register(Element)
admin.site.register(FeatureFlag)
admin.site.register(Action)
admin.site.register(ActionStep)
admin.site.register(Insight)
admin.site.register(InstanceSetting)


@admin.register(Plugin)
class PluginAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "organization_id",
        "is_global",
    )
    list_filter = ("plugin_type", "is_global")
    search_fields = ("name",)
    ordering = ("-created_at",)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "organization_link", "organization_id")
    search_fields = ("name", "organization__id", "organization__name")

    def organization_link(self, team: Team):
        return format_html(
            '<a href="/admin/posthog/organization/{}/change/">{}</a>', team.organization.pk, team.organization.name
        )


@admin.register(PluginConfig)
class PluginConfigAdmin(admin.ModelAdmin):
    list_display = (
        "plugin_id",
        "team_id",
    )
    ordering = ("-created_at",)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Define admin model for custom User model with no email field."""

    change_form_template = "loginas/change_form.html"

    fieldsets = (
        (None, {"fields": ("email", "password", "organization_name", "org_count")}),
        (_("Personal info"), {"fields": ("first_name", "last_name")}),
        (_("Permissions"), {"fields": ("is_active", "is_staff",)},),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
        (_("PostHog"), {"fields": ("temporary_token",)}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2"),}),)
    list_display = (
        "email",
        "first_name",
        "last_name",
        "organization_name",
        "org_count",
        "is_staff",
    )
    list_filter = ("is_staff", "is_active", "groups")
    search_fields = ("email", "first_name", "last_name")
    readonly_fields = ["organization_name", "org_count"]
    ordering = ("email",)

    def organization_name(self, user: User):
        if not user.organization:
            return "No Organization"

        return format_html(
            '<a href="/admin/posthog/organization/{}/change/">{}</a>', user.organization.pk, user.organization.name
        )

    def org_count(self, user: User) -> int:
        return user.organization_memberships.count()


class OrganizationMemberInline(admin.TabularInline):
    extra = 0
    model = Organization.members.through


class OrganizationTeamInline(admin.TabularInline):
    extra = 0
    model = Team

    fields = (
        "id",
        "displayed_name",
        "api_token",
        "app_urls",
        "name",
        "created_at",
        "updated_at",
        "anonymize_ips",
        "completed_snippet_onboarding",
        "ingested_event",
        "session_recording_opt_in",
        "signup_token",
        "is_demo",
        "access_control",
        "test_account_filters",
        "path_cleaning_filters",
        "timezone",
        "data_attributes",
        "correlation_config",
        "plugins_opt_in",
        "opt_out_capture",
    )
    readonly_fields = ("id", "displayed_name", "created_at", "updated_at")

    def displayed_name(self, team: Team):
        return format_html('<a href="/admin/posthog/team/{}/change/">{}. {}</a>', team.pk, team.pk, team.name)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    fields = [
        "name",
        "created_at",
        "updated_at",
        "plugins_access_level",
        "billing_plan",
        "organization_billing_link",
        "usage",
    ]
    inlines = [
        OrganizationTeamInline,
        OrganizationMemberInline,
    ]
    readonly_fields = ["created_at", "updated_at", "billing_plan", "organization_billing_link", "usage"]
    search_fields = ("name", "members__email")
    list_display = (
        "name",
        "created_at",
        "plugins_access_level",
        "members_count",
        "first_member",
        "organization_billing_link",
    )

    def members_count(self, organization: Organization):
        return organization.members.count()

    def first_member(self, organization: Organization):
        user = organization.members.order_by("id").first()
        return format_html(f'<a href="/admin/posthog/user/{user.pk}/change/">{user.email}</a>')

    def organization_billing_link(self, organization: Organization) -> str:
        return format_html(
            '<a href="/admin/multi_tenancy/organizationbilling/{}/change/">Billing →</a>', organization.pk
        )

    def usage(self, organization: Organization):
        return format_html(
            '<a target="_blank" href="/insights/new?insight=TRENDS&interval=day&display=ActionsLineGraph&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%2C%22math%22%3A%22dau%22%7D%5D&properties=%5B%7B%22key%22%3A%22organization_id%22%2C%22value%22%3A%22{}%22%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22person%22%7D%5D&actions=%5B%5D&new_entity=%5B%5D">See usage on PostHog →</a>',
            organization.id,
        )


class OrganizationBillingAdmin(admin.ModelAdmin):
    search_fields = ("name", "members__email")
