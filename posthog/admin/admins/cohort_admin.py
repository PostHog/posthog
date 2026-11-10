from urllib.parse import urlencode

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html

from products.cohorts.backend.facade.api import MAX_STATIC_COHORT_RESYNCS
from products.cohorts.backend.models.cohort import Cohort


@admin.register(Cohort)
class CohortAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "team_link",
        "is_static",
        "count",
        "is_calculating",
        "errors_calculating",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at",)
    actions = ["resync_static_cohort"]

    @admin.display(description="Team")
    def team_link(self, cohort: Cohort):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[cohort.team.pk]),
            cohort.team.name,
        )

    @admin.action(description="Re-sync static cohort from source query")
    def resync_static_cohort(self, request, queryset):
        # The confirm step lives in PostHog Admin, which previews the cohorts and asks for a reason.
        if queryset.count() > MAX_STATIC_COHORT_RESYNCS:
            self.message_user(
                request,
                f"Pick {MAX_STATIC_COHORT_RESYNCS} cohorts or fewer to re-sync them.",
                level=messages.ERROR,
            )
            return None
        query = urlencode([("cohort", str(cohort_id)) for cohort_id in queryset.values_list("id", flat=True)])
        return HttpResponseRedirect(
            f"{reverse('admin_console_tool_operation', args=['resave-cohorts', 'resync-static'])}?{query}"
        )
