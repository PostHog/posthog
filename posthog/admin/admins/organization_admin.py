from django.conf import settings
from django.contrib import admin
from django.core.management import call_command
from django.utils.html import format_html
from django.urls import reverse
from posthog.admin.inlines.organization_member_inline import OrganizationMemberInline
from posthog.admin.inlines.team_inline import TeamInline
from posthog.admin.paginators.no_count_paginator import NoCountPaginator
from django.utils import timezone
from datetime import timedelta

from posthog.models.organization import Organization
from django.urls import path
from django.shortcuts import render, redirect
from django.contrib import messages
from django import forms
from posthog.rbac.migrations.rbac_team_migration import rbac_team_access_control_migration
from posthog.rbac.migrations.rbac_feature_flag_migration import rbac_feature_flag_role_access_migration


class UsageReportForm(forms.Form):
    report_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))

    def clean_report_date(self):
        report_date = self.cleaned_data["report_date"]
        if report_date > (timezone.now().date() + timedelta(days=1)):
            raise forms.ValidationError("The date cannot be more than one day in the future.")
        return report_date


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
    inlines = [TeamInline, OrganizationMemberInline]
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
            format_html('<a href="{}">{}</a>', reverse("admin:posthog_user_change", args=[user.pk]), user.email)
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

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "send-usage-report/", self.admin_site.admin_view(self.send_usage_report_view), name="send-usage-report"
            ),
            path(
                "<str:organization_id>/run-rbac-team-migration/",
                self.admin_site.admin_view(self.run_rbac_team_migration),
                name="run-rbac-team-migration",
            ),
            path(
                "<str:organization_id>/run-rbac-feature-flag-migration/",
                self.admin_site.admin_view(self.run_rbac_feature_flag_migration),
                name="run-rbac-feature-flag-migration",
            ),
        ]
        return custom_urls + urls

    def send_usage_report_view(self, request):
        if not request.user.groups.filter(name="Billing Team").exists():
            messages.error(request, "You are not authorized to send usage reports.")
            return redirect(reverse("admin:posthog_organization_changelist"))

        if request.method == "POST":
            form = UsageReportForm(request.POST)
            if form.is_valid():
                report_date = form.cleaned_data["report_date"]
                call_command("send_usage_report", f"--date={report_date.strftime('%Y-%m-%d')}", "--async=1")
                messages.success(request, f"Usage report for date {report_date} was sent successfully.")
                return redirect(reverse("admin:posthog_organization_changelist"))
        else:
            form = UsageReportForm()

        return render(request, "admin/posthog/organization/send_usage_report.html", {"form": form})

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_usage_report_button"] = True
        return super().changelist_view(request, extra_context=extra_context)

    def run_rbac_team_migration(self, request, organization_id):
        if not request.user.groups.filter(name="Billing Team").exists():
            messages.error(request, "You are not authorized to run RBAC team migrations.")
            return redirect(reverse("admin:posthog_organization_changelist"))

        try:
            organization = Organization.objects.get(id=organization_id)
            rbac_team_access_control_migration(organization.id)
            messages.success(request, f"RBAC team migration completed successfully for {organization.name}")
        except Exception as e:
            messages.error(request, f"Error running RBAC team migration: {str(e)}")
        return redirect(reverse("admin:posthog_organization_change", args=[organization_id]))

    def run_rbac_feature_flag_migration(self, request, organization_id):
        if not request.user.groups.filter(name="Billing Team").exists():
            messages.error(request, "You are not authorized to run RBAC feature flag migrations.")
            return redirect(reverse("admin:posthog_organization_changelist"))

        try:
            organization = Organization.objects.get(id=organization_id)
            rbac_feature_flag_role_access_migration(organization.id)
            messages.success(request, f"RBAC feature flag migration completed successfully for {organization.name}")
        except Exception as e:
            messages.error(request, f"Error running RBAC feature flag migration: {str(e)}")
        return redirect(reverse("admin:posthog_organization_change", args=[organization_id]))

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        if request.user.groups.filter(name="Billing Team").exists():
            extra_context["show_rbac_migration_buttons"] = True

        return super().change_view(request, object_id, form_url, extra_context=extra_context)
