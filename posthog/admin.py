import json

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm as DjangoUserChangeForm
from django.contrib.auth.tokens import default_token_generator
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
    OrganizationMembership,
    Person,
    Plugin,
    PluginAttachment,
    PluginConfig,
    Team,
    User,
)

admin.site.register(Person)
admin.site.register(Element)
admin.site.register(FeatureFlag)
admin.site.register(Action)
admin.site.register(ActionStep)
admin.site.register(InstanceSetting)


@admin.register(Insight)
class InsightAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "short_id",
        "team",
        "organization",
        "created_at",
        "created_by",
    )
    search_fields = ("id", "name", "short_id", "team__name", "team__organization__name")
    ordering = ("-created_at",)

    def organization(self, insight: Insight):
        return insight.team.organization.name


@admin.register(Plugin)
class PluginAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "organization_id", "is_global")
    list_filter = ("plugin_type", "is_global")
    search_fields = ("name",)
    ordering = ("-created_at",)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "organization_link", "organization_id")
    search_fields = ("id", "name", "organization__id", "organization__name", "api_token")
    readonly_fields = ["primary_dashboard", "test_account_filters"]
    exclude = [
        "event_names",
        "event_names_with_usage",
        "plugins_opt_in",
        "event_properties",
        "event_properties_with_usage",
        "event_properties_numerical",
        "session_recording_retention_period_days",
    ]

    def organization_link(self, team: Team):
        return format_html(
            '<a href="/admin/posthog/organization/{}/change/">{}</a>', team.organization.pk, team.organization.name
        )


ATTACHMENT_PREVIEW_SIZE_LIMIT_BYTES = 1024 * 1024


class PluginAttachmentInline(admin.StackedInline):
    extra = 0
    model = PluginAttachment
    fields = ("key", "content_type", "file_size", "raw_contents", "json_contents")
    readonly_fields = fields

    def raw_contents(self, attachment: PluginAttachment):
        try:
            if attachment.file_size > ATTACHMENT_PREVIEW_SIZE_LIMIT_BYTES:
                raise ValueError(
                    f"file size {attachment.file_size} is larger than {ATTACHMENT_PREVIEW_SIZE_LIMIT_BYTES} bytes"
                )
            return attachment.contents.tobytes()
        except Exception as err:
            return format_html(f"cannot preview: {err}")

    def json_contents(self, attachment: PluginAttachment):
        try:
            if attachment.file_size > ATTACHMENT_PREVIEW_SIZE_LIMIT_BYTES:
                raise ValueError(
                    f"file size {attachment.file_size} is larger than {ATTACHMENT_PREVIEW_SIZE_LIMIT_BYTES} bytes"
                )
            return json.loads(attachment.contents.tobytes())
        except Exception as err:
            return format_html(f"cannot preview: {err}")

    def has_add_permission(self, request, obj):
        return False

    def has_change_permission(self, request, obj):
        return False

    def has_delete_permission(self, request, obj):
        return False


@admin.register(PluginConfig)
class PluginConfigAdmin(admin.ModelAdmin):
    list_select_related = ("plugin", "team")
    list_display = ("id", "plugin_name", "team_name", "enabled")
    list_filter = (
        ("enabled", admin.BooleanFieldListFilter),
        ("updated_at", admin.DateFieldListFilter),
        ("plugin", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ("team__name", "team__organization__name", "plugin__name")
    ordering = ("-created_at",)
    inlines = [PluginAttachmentInline]

    def plugin_name(self, config: PluginConfig):
        return format_html(f"{config.plugin.name} ({config.plugin_id})")

    def team_name(self, config: PluginConfig):
        return format_html(f"{config.team.name} ({config.team_id})")


class UserChangeForm(DjangoUserChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # This is a riff on https://github.com/django/django/blob/stable/4.1.x/django/contrib/auth/forms.py#L151-L153.
        # The difference from the Django default is that instead of a form where the _admin_ sets the new password,
        # we have a link to the password reset page which the _user_ can use themselves.
        # This way if some user needs to reset their password and there's a problem with receiving the reset link email,
        # an admin can provide that reset link manually – much better than sending a new password in plain text.
        password_reset_token = default_token_generator.make_token(self.instance)
        self.fields["password"].help_text = (
            "Raw passwords are not stored, so there is no way to see this user’s password, but you can send them "
            f'<a target="_blank" href="/reset/{self.instance.uuid}/{password_reset_token}">this password reset link</a> '
            "(it only works when logged out)."
        )


class OrganizationMemberInline(admin.TabularInline):
    extra = 0
    model = OrganizationMembership
    readonly_fields = ("user", "joined_at", "updated_at")
    autocomplete_fields = ("user", "organization")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Define admin model for custom User model with no email field."""

    form = UserChangeForm
    change_password_form = None  # This view is not exposed in our subclass of UserChangeForm
    change_form_template = "loginas/change_form.html"

    inlines = [OrganizationMemberInline]
    fieldsets = (
        (None, {"fields": ("email", "password", "current_organization", "is_email_verified", "pending_email")}),
        (_("Personal info"), {"fields": ("first_name", "last_name")}),
        (_("Permissions"), {"fields": ("is_active", "is_staff")}),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
        (_("Toolbar authentication"), {"fields": ("temporary_token",)}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)
    list_display = ("email", "first_name", "last_name", "current_organization", "is_staff")
    list_filter = ("is_staff", "is_active", "groups")
    search_fields = ("email", "first_name", "last_name")
    readonly_fields = ["current_organization"]
    ordering = ("email",)

    def current_organization(self, user: User):
        if not user.organization:
            return "None"

        return format_html(
            '<a href="/admin/posthog/organization/{}/change/">{}</a>', user.organization.pk, user.organization.name
        )


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
        "autocapture_opt_out",
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
        "billing_link_v2",
        "usage_posthog",
        "usage",
    ]
    inlines = [OrganizationTeamInline, OrganizationMemberInline]
    readonly_fields = [
        "created_at",
        "updated_at",
        "billing_plan",
        "organization_billing_link",
        "billing_link_v2",
        "usage_posthog",
        "usage",
    ]
    search_fields = ("name", "members__email", "team__api_token")
    list_display = (
        "name",
        "created_at",
        "plugins_access_level",
        "members_count",
        "first_member",
        "organization_billing_link",
        "billing_link_v2",
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

    def billing_link_v2(self, organization: Organization) -> str:
        if not organization.has_billing_v2_setup:
            return ""
        url = f"{settings.BILLING_SERVICE_URL}/admin/billing/customer/?q={organization.pk}"
        return format_html(f'<a href="{url}">Billing V2 →</a>')

    def usage_posthog(self, organization: Organization):
        return format_html(
            '<a target="_blank" href="/insights/new?insight=TRENDS&interval=day&display=ActionsLineGraph&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%2C%22math%22%3A%22dau%22%7D%5D&properties=%5B%7B%22key%22%3A%22organization_id%22%2C%22value%22%3A%22{}%22%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22person%22%7D%5D&actions=%5B%5D&new_entity=%5B%5D">See usage on PostHog →</a>',
            organization.id,
        )


class OrganizationBillingAdmin(admin.ModelAdmin):
    search_fields = ("name", "members__email")
