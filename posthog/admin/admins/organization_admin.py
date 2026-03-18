from datetime import UTC, timedelta

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.management import call_command
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.module_loading import import_string
from django.utils.safestring import mark_safe

from posthog.admin.inlines.organization_domain_inline import OrganizationDomainInline
from posthog.admin.inlines.organization_invite_inline import OrganizationInviteInline
from posthog.admin.inlines.organization_member_inline import OrganizationMemberInline
from posthog.admin.inlines.project_inline import ProjectInline
from posthog.admin.inlines.team_inline import TeamInline
from posthog.admin.paginators.no_count_paginator import NoCountPaginator
from posthog.models.organization import Organization

# Registry of models to count for bulk-delete report.
# Format: (model_import_path, filter_field, display_name)
# This mirrors delete_bulky_postgres_data() in posthog/models/team/util.py
# When bulk-delete changes, update this list accordingly.
# Note: CohortPeople and BatchExport require special handling (see below)
BULK_DELETE_MODEL_REGISTRY: tuple[tuple[str, str, str], ...] = (
    ("products.early_access_features.backend.models.EarlyAccessFeature", "team_id", "Early Access Features"),
    ("posthog.models.person.PersonDistinctId", "team_id", "Person Distinct IDs"),
    ("posthog.models.person.PersonlessDistinctId", "team_id", "Personless Distinct IDs"),
    (
        "products.error_tracking.backend.models.ErrorTrackingIssueFingerprintV2",
        "team_id",
        "Error Tracking Fingerprints",
    ),
    ("posthog.models.feature_flag.feature_flag.FeatureFlagHashKeyOverride", "team_id", "Feature Flag Overrides"),
    ("posthog.models.group.group.Group", "team_id", "Groups"),
    ("posthog.models.group_type_mapping.GroupTypeMapping", "team_id", "Group Type Mappings"),
    ("posthog.models.person.Person", "team_id", "Persons"),
    ("posthog.models.insight_caching_state.InsightCachingState", "team_id", "Insight Caching States"),
)


def get_model_counts_for_organization(organization: Organization) -> list[dict]:
    """
    Returns counts of all bulk-delete models for teams in this organization.
    """
    from posthog.models.cohort import Cohort, CohortPeople

    team_ids = list(organization.teams.values_list("id", flat=True))
    if not team_ids:
        return []

    results = []
    for model_path, filter_field, display_name in BULK_DELETE_MODEL_REGISTRY:
        try:
            model_class = import_string(model_path)
            count = model_class.objects.filter(**{f"{filter_field}__in": team_ids}).count()
            results.append(
                {
                    "name": display_name,
                    "count": count,
                    "model": model_class._meta.label,
                }
            )
        except Exception as e:
            results.append(
                {
                    "name": display_name,
                    "count": f"Error: {e}",
                    "model": model_path,
                }
            )

    # CohortPeople is in persons_db, Cohort is in default db - can't do cross-db JOIN
    # Must first get cohort_ids from default db, then count CohortPeople by cohort_id
    try:
        cohort_ids = list(Cohort.objects.filter(team_id__in=team_ids).values_list("id", flat=True))
        cohort_people_count = CohortPeople.objects.filter(cohort_id__in=cohort_ids).count() if cohort_ids else 0
        results.append(
            {
                "name": "Cohort People",
                "count": cohort_people_count,
                "model": CohortPeople._meta.label,
            }
        )
    except Exception as e:
        results.append(
            {
                "name": "Cohort People",
                "count": f"Error: {e}",
                "model": "posthog.models.cohort.CohortPeople",
            }
        )

    # BatchExport requires deleted=False filter to match delete_batch_exports() behavior
    try:
        from posthog.batch_exports.models import BatchExport

        batch_export_count = BatchExport.objects.filter(team_id__in=team_ids, deleted=False).count()
        results.append(
            {
                "name": "Batch Exports",
                "count": batch_export_count,
                "model": BatchExport._meta.label,
            }
        )
    except Exception as e:
        results.append(
            {
                "name": "Batch Exports",
                "count": f"Error: {e}",
                "model": "posthog.batch_exports.models.BatchExport",
            }
        )

    return sorted(results, key=lambda x: x["name"])


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
        "usage_display",
        "limited_products_display",
        "customer_trust_scores",
        "bulk_delete_data_display",
        "is_active",
        "is_not_active_reason",
        "is_hipaa",
        "is_platform",
        "members_can_invite",
    ]
    inlines = [ProjectInline, TeamInline, OrganizationMemberInline, OrganizationInviteInline, OrganizationDomainInline]
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
                {"limited": limited, "organization_id": organization.id, "total_teams": total_teams},
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
            if product == "period":
                continue
            formatted_data[product] = {
                "usage": f"{int(data.get('usage', 0)):,}" if data.get("usage") is not None else "-",
                "limit": f"{int(data.get('limit')):,}" if data.get("limit") else None,
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
        url = reverse("admin:organization_model_counts", args=[organization.pk])
        return format_html('<a class="button" href="{}">View counts</a>', url)

    def limit_product_view(self, request, organization_id):
        from ee.billing.quota_limiting import QuotaResource

        organization: Organization = Organization.objects.get(id=organization_id)
        assert organization

        if request.method == "POST":
            resource_name = request.POST.get("resource")
            try:
                resource = QuotaResource(resource_name)
                organization.limit_product_until_end_of_billing_cycle(resource)
                messages.success(request, f"Successfully limited {resource_name} for organization {organization.name}")
            except ValueError:
                messages.error(request, f"Invalid resource: {resource_name}")
            except Exception as e:
                messages.error(request, f"Error limiting {resource_name}: {str(e)}")

        return redirect(reverse("admin:posthog_organization_change", args=[organization_id]))

    def unlimit_product_view(self, request, organization_id):
        from ee.billing.quota_limiting import QuotaResource

        organization = Organization.objects.get(id=organization_id)

        if request.method == "POST":
            resource_name = request.POST.get("resource")
            try:
                resource = QuotaResource(resource_name)
                organization.unlimit_product(resource)
                messages.success(
                    request, f"Successfully unlimited {resource_name} for organization {organization.name}"
                )
            except ValueError:
                messages.error(request, f"Invalid resource: {resource_name}")
            except Exception as e:
                messages.error(request, f"Error unlimiting {resource_name}: {str(e)}")

        return redirect(reverse("admin:posthog_organization_change", args=[organization_id]))

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "send-usage-report/", self.admin_site.admin_view(self.send_usage_report_view), name="send-usage-report"
            ),
            path(
                "<path:organization_id>/limit-product/",
                self.admin_site.admin_view(self.limit_product_view),
                name="limit_product",
            ),
            path(
                "<path:organization_id>/unlimit-product/",
                self.admin_site.admin_view(self.unlimit_product_view),
                name="unlimit_product",
            ),
            path(
                "<path:organization_id>/model-counts/",
                self.admin_site.admin_view(self.model_counts_view),
                name="organization_model_counts",
            ),
        ]
        return custom_urls + urls

    def model_counts_view(self, request, organization_id):
        organization = Organization.objects.get(id=organization_id)
        counts = get_model_counts_for_organization(organization)
        total = sum(c["count"] for c in counts if isinstance(c["count"], int))

        return render(
            request,
            "admin/organization/model_counts.html",
            {
                "organization": organization,
                "counts": counts,
                "total": total,
            },
        )

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

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        # Store request for access in display methods (needed for CSRF tokens in templates)
        self._current_request = request
        return super().change_view(request, object_id, form_url, extra_context=extra_context)
