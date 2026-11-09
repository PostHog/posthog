from datetime import UTC

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_http_methods

from posthog.admin.ai_training_opt_in_history import get_ai_training_opt_in_history
from posthog.admin.console.moved import MovedToConsole
from posthog.admin.console.usage_reports_tool import ReportDateForm
from posthog.admin.inline_registry import extra_inlines_for
from posthog.admin.inlines.events_retention_config_inline import OrganizationEventsRetentionConfigInline
from posthog.admin.inlines.organization_domain_inline import OrganizationDomainInline
from posthog.admin.inlines.organization_invite_inline import OrganizationInviteInline
from posthog.admin.inlines.organization_member_inline import OrganizationMemberInline
from posthog.admin.inlines.project_inline import ProjectInline
from posthog.admin.inlines.proxy_record_inline import ProxyRecordInline
from posthog.admin.inlines.team_inline import TeamInline
from posthog.admin.paginators.no_count_paginator import NoCountPaginator
from posthog.models.organization import Organization
from posthog.tasks.ai_observability_usage_report import internal_reporting_team_id

from products.ai_observability.backend.facade.admin import dataset_retention_enabled, set_dataset_retention_enabled


class DatasetRetentionForm(forms.Form):
    enabled = forms.TypedChoiceField(
        label="Dataset cleanup",
        choices=[("enabled", "Enabled"), ("disabled", "Disabled")],
        coerce=lambda value: value == "enabled",
        widget=forms.RadioSelect,
    )


@admin.register(Organization)
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

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = {
            **(extra_context or {}),
            "deactivation_reason_presets": list(Organization.DeactivationReason.values),
        }
        return super().changeform_view(request, object_id, form_url, extra_context)

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

        # Access request stored during change_view
        request = getattr(self, "_current_request", None)
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
                request=request,
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

        # Access request stored during change_view
        request = getattr(self, "_current_request", None)
        # nosemgrep: python.django.security.audit.avoid-mark-safe.avoid-mark-safe (admin-only, renders trusted template)
        return mark_safe(
            render_to_string(
                "admin/organization/usage_display.html",
                {"usage_data": formatted_data, "period_info": period_info},
                request=request,
            )
        )

    @admin.display(description="Child model counts")
    def bulk_delete_data_display(self, organization: Organization):
        if not organization.pk:
            return "-"
        return MovedToConsole.action("organization", organization, "deletion", "Child model counts")

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

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "send-ai-observability-usage-report/",
                self.admin_site.admin_view(self.send_ai_observability_usage_report_view),
                name="send-ai-observability-usage-report",
            ),
            path(
                "ai-observability-dataset-retention/",
                self.admin_site.admin_view(self.dataset_retention_view),
                name="ai-observability-dataset-retention",
            ),
        ]
        return custom_urls + urls

    def send_ai_observability_usage_report_view(self, request):
        # Staff-only on purpose, unlike the sibling billing view: nothing here is customer-facing, and
        # the task now skips organizations that already have a report for the period.
        if request.method == "POST":
            form = ReportDateForm(request.POST)
            if form.is_valid():
                report_date = form.cleaned_data["report_date"]
                try:
                    call_command(
                        "send_ai_observability_usage_report", f"--date={report_date.strftime('%Y-%m-%d')}", "--async"
                    )
                except CommandError as e:
                    # Surfacing this matters: a swallowed refusal would report success for a run that
                    # never started, so the operator would stop looking for the missing reports.
                    messages.error(request, str(e))
                else:
                    messages.success(request, f"AI observability usage report for date {report_date} was queued.")
                return redirect(reverse("admin:posthog_organization_changelist"))
        else:
            form = ReportDateForm()

        return render(
            request,
            "admin/posthog/organization/send_ai_observability_usage_report.html",
            {"form": form, "can_skip_existing_reports": internal_reporting_team_id() is not None},
        )

    @method_decorator(require_http_methods(["GET", "POST"]))
    def dataset_retention_view(self, request: HttpRequest) -> HttpResponse:
        user_id = request.user.pk
        if user_id is None or not request.user.has_perm("posthog.change_instancesetting"):
            raise PermissionDenied
        enabled = dataset_retention_enabled()
        form = DatasetRetentionForm(
            request.POST if request.method == "POST" else None,
            initial={"enabled": "enabled" if enabled else "disabled"},
        )
        if request.method == "POST" and form.is_valid():
            new_enabled = form.cleaned_data["enabled"]
            set_dataset_retention_enabled(enabled=new_enabled, user_id=user_id)
            messages.success(
                request, f"Dataset cleanup is now {'enabled' if new_enabled else 'disabled'} in this region."
            )
            return redirect(reverse("admin:ai-observability-dataset-retention"))
        return TemplateResponse(
            request,
            "admin/posthog/organization/ai_observability_dataset_retention.html",
            {
                **self.admin_site.each_context(request),
                "title": "AI observability dataset retention",
                "form": form,
                "enabled": enabled,
            },
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        # Store request for access in display methods (needed for CSRF tokens in templates)
        self._current_request = request
        return super().change_view(request, object_id, form_url, extra_context=extra_context)
