from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html

from posthog.models import Cohort


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
        from posthog.tasks.calculate_cohort import insert_cohort_from_query

        for cohort in queryset:
            if not cohort.is_static:
                self.message_user(
                    request,
                    f"Cohort {cohort.id} ({cohort.name}) is not static, skipping.",
                    messages.WARNING,
                )
                continue

            if not cohort.query:
                self.message_user(
                    request,
                    f"Cohort {cohort.id} ({cohort.name}) has no source query, skipping.",
                    messages.WARNING,
                )
                continue

            old_count = cohort.count
            insert_cohort_from_query.delay(cohort.pk, cohort.team_id)
            self.message_user(
                request,
                f"Queued re-sync for cohort {cohort.id} ({cohort.name}), current count: {old_count}.",
                messages.SUCCESS,
            )
