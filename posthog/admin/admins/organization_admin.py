from datetime import UTC

from django import forms
from django.conf import settings
from django.contrib import admin
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from posthog.admin.ai_training_opt_in_history import get_ai_training_opt_in_history
from posthog.admin.console.moved import MovedToConsole
from posthog.admin.console.organization_deletion_panels import data_tool_url
from posthog.admin.inline_registry import extra_inlines_for
from posthog.admin.inlines.events_retention_config_inline import OrganizationEventsRetentionConfigInline
from posthog.admin.inlines.organization_domain_inline import OrganizationDomainInline
from posthog.admin.inlines.organization_invite_inline import OrganizationInviteInline
from posthog.admin.inlines.organization_ip_restrictions_inline import OrganizationIPRestrictionsInline
from posthog.admin.inlines.organization_member_inline import OrganizationMemberInline
from posthog.admin.inlines.project_inline import ProjectInline
from posthog.admin.inlines.proxy_record_inline import ProxyRecordInline
from posthog.admin.inlines.team_inline import TeamInline
from posthog.admin.paginators.no_count_paginator import NoCountPaginator
from posthog.models.organization import Organization


class DatalistTextInput(forms.TextInput):
    """A text input that suggests values from a list, and still takes any text."""

    def __init__(self, suggestions: list[str], attrs: dict[str, str] | None = None) -> None:
        super().__init__(attrs)
        self.suggestions = suggestions

    def render(self, name, value, attrs=None, renderer=None):
        list_id = f"{(attrs or {}).get('id', name)}_suggestions"
        text_input = super().render(name, value, {**(attrs or {}), "list": list_id}, renderer)
        options = format_html_join(
            "", '<option value="{}"></option>', ((suggestion,) for suggestion in self.suggestions)
        )
        return format_html('{}<datalist id="{}">{}</datalist>', text_input, list_id, options)


class OrganizationAdminForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = "__all__"
        widgets = {
            "is_not_active_reason": DatalistTextInput(
                suggestions=list(Organization.DeactivationReason.values), attrs={"size": "60"}
            )
        }


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    form = OrganizationAdminForm
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
        "usage_display",
        "limited_products_display",
        "customer_trust_scores",
        "bulk_delete_data_display",
        "sync_to_billing_display",
        "is_active",
        "is_not_active_reason",
        "is_platform",
        "members_can_invite",
        "members_can_create_projects",
        "uses_most_specific_access_resolution",
        "is_ai_data_processing_approved",
        "is_ai_training_opted_in",
        "is_ai_training_locked",
        "is_ai_training_cta_shown",
        "ai_training_opt_in_history_display",
        "trigger_deletion_display",
    ]
    inlines = [
        ProjectInline,
        TeamInline,
        OrganizationMemberInline,
        OrganizationInviteInline,
        OrganizationDomainInline,
        OrganizationIPRestrictionsInline,
        ProxyRecordInline,
        OrganizationEventsRetentionConfigInline,
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "billing_link",
        "usage_posthog",
        "usage_display",
        "limited_products_display",
        "customer_trust_scores",
        "bulk_delete_data_display",
        "sync_to_billing_display",
        "ai_training_opt_in_history_display",
        "trigger_deletion_display",
    ]
    search_fields = ("id", "name", "members__email", "team__api_token")
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

    def get_inlines(self, request, obj=None):
        # Inlines other apps registered for Organization, so a product can show a panel on
        # this page without core importing it. See posthog.admin.inline_registry.
        return [*super().get_inlines(request, obj), *extra_inlines_for(Organization)]

    def members_count(self, organization: Organization):
        return organization.members.count()

    def first_member(self, organization: Organization):
        user = organization.members.order_by("id").first()
        return (
            format_html('<a href="{}">{}</a>', reverse("admin:posthog_user_change", args=[user.pk]), user.email)
            if user is not None
            else "None"
        )

    def billing_link(self, organization: Organization) -> str:
        url = f"{settings.BILLING_SERVICE_URL}/admin/billing/customer/?q={organization.pk}"
        return format_html('<a href="{}">Billing →</a>', url)

    def usage_posthog(self, organization: Organization):
        return format_html(
            '<a target="_blank" href="/insights/new?insight=TRENDS&interval=day&display=ActionsLineGraph&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%2C%22math%22%3A%22dau%22%7D%5D&properties=%5B%7B%22key%22%3A%22organization_id%22%2C%22value%22%3A%22{}%22%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22person%22%7D%5D&actions=%5B%5D&new_entity=%5B%5D">See usage on PostHog →</a>',
            organization.id,
        )

    @admin.display(description="Limited Products")
    def limited_products_display(self, organization: Organization):
        from datetime import datetime

        limited = organization.get_limited_products()
        total_teams = organization.teams.count()

        # Format Unix timestamps to human-readable dates
        for _resource, info in limited.items():
            redis_until = info.get("redis_quota_limited_until")
            if redis_until and redis_until != 0:
                try:
                    dt = datetime.fromtimestamp(redis_until, tz=UTC)
                    info["redis_quota_limited_until_formatted"] = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                except (ValueError, OSError, OverflowError):
                    info["redis_quota_limited_until_formatted"] = str(redis_until)
            else:
                info["redis_quota_limited_until_formatted"] = "-"

            usage_until = info.get("usage_quota_limited_until")
            if usage_until and usage_until != 0:
                try:
                    dt = datetime.fromtimestamp(usage_until, tz=UTC)
                    info["usage_quota_limited_until_formatted"] = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                except (ValueError, OSError, OverflowError):
                    info["usage_quota_limited_until_formatted"] = str(usage_until)
            else:
                info["usage_quota_limited_until_formatted"] = "-"

        # nosemgrep: python.django.security.audit.avoid-mark-safe.avoid-mark-safe (admin-only, renders trusted template)
        return mark_safe(
            render_to_string(
                "admin/organization/limited_products.html",
                {
                    "limited": limited,
                    "total_teams": total_teams,
                    "actions_moved": MovedToConsole.action(
                        "organization", organization, "billing", "Limit and unlimit"
                    ),
                },
            )
        )

    @admin.display(description="Usage")
    def usage_display(self, organization: Organization):
        import dateutil.parser

        usage_data = organization.usage or {}
        period_info = None

        # Parse and format billing period
        if usage_data.get("period"):
            try:
                period = usage_data["period"]
                start_dt = dateutil.parser.isoparse(period[0])
                end_dt = dateutil.parser.isoparse(period[1])

                # Calculate days remaining
                now = timezone.now()
                days_remaining = (end_dt - now).days

                period_info = {
                    "start": start_dt.strftime("%Y-%m-%d"),
                    "end": end_dt.strftime("%Y-%m-%d"),
                    "days_remaining": max(0, days_remaining),
                }
            except (ValueError, IndexError, AttributeError):
                pass

        # Format numbers with thousand separators
        formatted_data = {}
        for product, data in usage_data.items():
            # `period` and the billing status stamps sit next to the products and are not dicts.
            if not isinstance(data, dict):
                continue
            limit = data.get("limit")
            formatted_data[product] = {
                "usage": f"{int(data.get('usage', 0)):,}" if data.get("usage") is not None else "-",
                "limit": f"{int(limit):,}" if limit else None,
                "todays_usage": f"{int(data.get('todays_usage', 0)):,}"
                if data.get("todays_usage") is not None
                else "-",
                "usage_raw": data.get("usage"),
                "limit_raw": data.get("limit"),
            }

        # nosemgrep: python.django.security.audit.avoid-mark-safe.avoid-mark-safe (admin-only, renders trusted template)
        return mark_safe(
            render_to_string(
                "admin/organization/usage_display.html",
                {"usage_data": formatted_data, "period_info": period_info},
            )
        )

    @admin.display(description="Child model counts")
    def bulk_delete_data_display(self, organization: Organization):
        if not organization.pk:
            return "-"
        return format_html(
            '<a href="{}">Child model counts: now in PostHog Admin &#8599;</a>', data_tool_url(organization)
        )

    @admin.display(description="AI training opt-in history")
    def ai_training_opt_in_history_display(self, organization: Organization):
        # UUIDT sets the id before the save, so the add form's unsaved instance also has a pk.
        if organization._state.adding:
            return "-"
        # render_to_string returns a SafeString, so this method does not need mark_safe.
        return render_to_string(
            "admin/organization/ai_training_opt_in_history.html",
            {"history": get_ai_training_opt_in_history(organization)},
        )

    @admin.display(description="Sync to billing")
    def sync_to_billing_display(self, organization: Organization):
        if not organization.pk:
            return "-"
        return MovedToConsole.action("organization", organization, "billing", "Sync members to billing")

    @admin.display(description="Danger zone")
    def trigger_deletion_display(self, organization: Organization):
        if not organization.pk:
            return "-"
        return MovedToConsole.action("organization", organization, "deletion", "Trigger deletion")
