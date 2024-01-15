import json

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm as DjangoUserChangeForm
from django.contrib.auth.tokens import default_token_generator
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django_otp.plugins.otp_totp.models import TOTPDevice

from posthog.models import (
    Action,
    AsyncDeletion,
    Cohort,
    Dashboard,
    DashboardTile,
    Experiment,
    FeatureFlag,
    GroupTypeMapping,
    Insight,
    InstanceSetting,
    Organization,
    OrganizationMembership,
    Person,
    PersonDistinctId,
    Plugin,
    PluginAttachment,
    PluginConfig,
    Survey,
    Team,
    Text,
    User,
)
from posthog.warehouse.models import DataWarehouseTable


class DashboardTileInline(admin.TabularInline):
    extra = 0
    model = DashboardTile
    autocomplete_fields = ("insight", "text")
    readonly_fields = ("filters_hash",)


class TOTPDeviceInline(admin.TabularInline):
    model = TOTPDevice
    extra = 0


@admin.register(Dashboard)
class DashboardAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "team_link",
        "organization_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    readonly_fields = (
        "last_accessed_at",
        "deprecated_tags",
        "deprecated_tags_v2",
        "share_token",
    )
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at", "creation_mode")
    inlines = (DashboardTileInline,)

    def team_link(self, dashboard: Dashboard):
        return format_html(
            '<a href="/admin/posthog/team/{}/change/">{}</a>',
            dashboard.team.pk,
            dashboard.team.name,
        )

    def organization_link(self, dashboard: Dashboard):
        return format_html(
            '<a href="/admin/posthog/organization/{}/change/">{}</a>',
            dashboard.team.organization.pk,
            dashboard.team.organization.name,
        )


@admin.register(DataWarehouseTable)
class DataWarehouseTableAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "format",
        "url_pattern",
        "team_link",
        "organization_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at",)

    def team_link(self, dashboard: Dashboard):
        return format_html(
            '<a href="/admin/posthog/team/{}/change/">{}</a>',
            dashboard.team.pk,
            dashboard.team.name,
        )

    def organization_link(self, dashboard: Dashboard):
        return format_html(
            '<a href="/admin/posthog/organization/{}/change/">{}</a>',
            dashboard.team.organization.pk,
            dashboard.team.organization.name,
        )


@admin.register(Text)
class TextAdmin(admin.ModelAdmin):
    autocomplete_fields = ("created_by", "last_modified_by", "team")
    search_fields = ("id", "body", "team__name", "team__organization__name")


@admin.register(Insight)
class InsightAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "short_id",
        "effective_name",
        "team_link",
        "organization_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "short_id", "effective_name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "short_id", "team__name", "team__organization__name")
    readonly_fields = ("deprecated_tags", "deprecated_tags_v2", "dive_dashboard")
    autocomplete_fields = ("team", "dashboard", "created_by", "last_modified_by")
    ordering = ("-created_at",)

    def effective_name(self, insight: Insight):
        return insight.name or format_html("<i>{}</>", insight.derived_name)

    def team_link(self, insight: Insight):
        return format_html(
            '<a href="/admin/posthog/team/{}/change/">{}</a>',
            insight.team.pk,
            insight.team.name,
        )

    def organization_link(self, insight: Insight):
        return format_html(
            '<a href="/admin/posthog/organization/{}/change/">{}</a>',
            insight.team.organization.pk,
            insight.team.organization.name,
        )


@admin.register(Plugin)
class PluginAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "organization_id", "is_global")
    list_display_links = ("id", "name")
    list_filter = ("plugin_type", "is_global")
    autocomplete_fields = ("organization",)
    search_fields = ("name",)
    ordering = ("-created_at",)


class ActionInline(admin.TabularInline):
    extra = 0
    model = Action
    classes = ("collapse",)
    autocomplete_fields = ("created_by",)


class GroupTypeMappingInline(admin.TabularInline):
    extra = 0
    model = GroupTypeMapping
    fields = ("group_type_index", "group_type", "name_singular", "name_plural")
    readonly_fields = fields
    classes = ("collapse",)
    max_num = 5
    min_num = 5


@admin.register(Cohort)
class CohortAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "team_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at",)

    def team_link(self, cohort: Cohort):
        return format_html(
            '<a href="/admin/posthog/team/{}/change/">{}</a>',
            cohort.team.pk,
            cohort.team.name,
        )


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "key",
        "team_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "key")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "key", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at",)

    def team_link(self, flag: FeatureFlag):
        return format_html(
            '<a href="/admin/posthog/team/{}/change/">{}</a>',
            flag.team.pk,
            flag.team.name,
        )


@admin.register(Experiment)
class ExperimentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "team_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at",)

    def team_link(self, experiment: Experiment):
        return format_html(
            '<a href="/admin/posthog/team/{}/change/">{}</a>',
            experiment.team.pk,
            experiment.team.name,
        )


@admin.register(Survey)
class SurveyAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "team_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at",)

    def team_link(self, experiment: Experiment):
        return format_html(
            '<a href="/admin/posthog/team/{}/change/">{}</a>',
            experiment.team.pk,
            experiment.team.name,
        )


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "organization_link",
        "organization_id",
        "created_at",
        "updated_at",
    )
    list_display_links = ("id", "name")
    list_select_related = ("organization",)
    search_fields = (
        "id",
        "name",
        "organization__id",
        "organization__name",
        "api_token",
    )
    readonly_fields = ["organization", "primary_dashboard", "test_account_filters"]
    inlines = [GroupTypeMappingInline, ActionInline]
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "name",
                    "organization",
                ],
            },
        ),
        (
            "General",
            {
                "classes": ["collapse"],
                "fields": [
                    "api_token",
                    "timezone",
                    "slack_incoming_webhook",
                    "primary_dashboard",
                ],
            },
        ),
        (
            "Onboarding",
            {
                "classes": ["collapse"],
                "fields": [
                    "is_demo",
                    "completed_snippet_onboarding",
                    "ingested_event",
                    "signup_token",
                ],
            },
        ),
        (
            "Settings",
            {
                "classes": ["collapse"],
                "fields": [
                    "anonymize_ips",
                    "autocapture_opt_out",
                    "autocapture_exceptions_opt_in",
                    "session_recording_opt_in",
                    "capture_console_log_opt_in",
                    "capture_performance_opt_in",
                    "session_recording_sample_rate",
                    "session_recording_minimum_duration_milliseconds",
                    "session_recording_linked_flag",
                    "data_attributes",
                    "session_recording_version",
                    "access_control",
                    "inject_web_apps",
                    "extra_settings",
                ],
            },
        ),
        (
            "Filters",
            {
                "classes": ["collapse"],
                "fields": [
                    "test_account_filters",
                    "test_account_filters_default_checked",
                    "path_cleaning_filters",
                ],
            },
        ),
    ]

    def organization_link(self, team: Team):
        return format_html(
            '<a href="/admin/posthog/organization/{}/change/">{}</a>',
            team.organization.pk,
            team.organization.name,
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
    list_display_links = ("id", "plugin_name")
    list_filter = (
        ("enabled", admin.BooleanFieldListFilter),
        ("updated_at", admin.DateFieldListFilter),
        ("plugin", admin.RelatedOnlyFieldListFilter),
    )
    list_select_related = ("team", "plugin")
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

    inlines = [OrganizationMemberInline, TOTPDeviceInline]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "email",
                    "password",
                    "current_organization",
                    "is_email_verified",
                    "pending_email",
                    "strapi_id",
                )
            },
        ),
        (_("Personal info"), {"fields": ("first_name", "last_name")}),
        (_("Permissions"), {"fields": ("is_active", "is_staff")}),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
        (_("Toolbar authentication"), {"fields": ("temporary_token",)}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)
    list_display = (
        "id",
        "email",
        "first_name",
        "last_name",
        "current_team_link",
        "current_organization_link",
        "is_staff",
    )
    list_display_links = ("id", "email")
    list_filter = ("is_staff", "is_active", "groups")
    list_select_related = ("current_team", "current_organization")
    search_fields = ("email", "first_name", "last_name")
    readonly_fields = ["current_team", "current_organization"]
    ordering = ("email",)

    def current_team_link(self, user: User):
        if not user.team:
            return "–"

        return format_html(
            '<a href="/admin/posthog/team/{}/change/">{}</a>',
            user.team.pk,
            user.team.name,
        )

    def current_organization_link(self, user: User):
        if not user.organization:
            return "–"

        return format_html(
            '<a href="/admin/posthog/organization/{}/change/">{}</a>',
            user.organization.pk,
            user.organization.name,
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
        return format_html(
            '<a href="/admin/posthog/team/{}/change/">{}. {}</a>',
            team.pk,
            team.pk,
            team.name,
        )


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    date_hierarchy = "created_at"
    fields = [
        "name",
        "created_at",
        "updated_at",
        "plugins_access_level",
        "billing_link_v2",
        "usage_posthog",
        "usage",
    ]
    inlines = [OrganizationTeamInline, OrganizationMemberInline]
    readonly_fields = [
        "created_at",
        "updated_at",
        "billing_link_v2",
        "usage_posthog",
        "usage",
    ]
    search_fields = ("name", "members__email", "team__api_token")
    list_display = (
        "id",
        "name",
        "created_at",
        "plugins_access_level",
        "members_count",
        "first_member",
        "billing_link_v2",
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

    def billing_link_v2(self, organization: Organization) -> str:
        url = f"{settings.BILLING_SERVICE_URL}/admin/billing/customer/?q={organization.pk}"
        return format_html(f'<a href="{url}">Billing V2 →</a>')

    def usage_posthog(self, organization: Organization):
        return format_html(
            '<a target="_blank" href="/insights/new?insight=TRENDS&interval=day&display=ActionsLineGraph&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%2C%22math%22%3A%22dau%22%7D%5D&properties=%5B%7B%22key%22%3A%22organization_id%22%2C%22value%22%3A%22{}%22%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22person%22%7D%5D&actions=%5B%5D&new_entity=%5B%5D">See usage on PostHog →</a>',
            organization.id,
        )


class OrganizationBillingAdmin(admin.ModelAdmin):
    search_fields = ("name", "members__email")


@admin.register(InstanceSetting)
class InstanceSettingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "key",
        "value",
    )


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "distinct_ids",
        "created_at",
        "team",
        "is_user",
        "is_identified",
        "version",
    )
    list_filter = ("created_at", "is_identified", "version")
    search_fields = ("id",)


@admin.register(PersonDistinctId)
class PersonDistinctIdAdmin(admin.ModelAdmin):
    list_display = ("id", "team", "distinct_id", "version")
    list_filter = ("version",)
    search_fields = ("id", "distinct_id")


@admin.register(AsyncDeletion)
class AsyncDeletionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "deletion_type",
        "group_type_index",
        "team_id",
        "key",
        "created_by",
        "created_at",
        "delete_verified_at",
    )
    list_filter = ("deletion_type", "delete_verified_at")
    search_fields = ("key",)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
