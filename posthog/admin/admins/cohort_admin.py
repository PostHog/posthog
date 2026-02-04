from django.contrib import admin, messages
from django.db.models import F
from django.urls import reverse
from django.utils.html import format_html

from posthog.models import Cohort
from posthog.models.cohort.util import CohortValidationError, validate_cohort_for_recalculation
from posthog.tasks.calculate_cohort import increment_version_and_enqueue_calculate_cohort


class CohortAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "team_link",
        "created_at",
        "created_by",
        "is_calculating",
        "last_calculation",
        "errors_calculating",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at",)
    actions = ["recalculate_cohorts", "reset_stuck_cohorts"]
    list_filter = ["is_calculating", "is_static", "deleted"]

    @admin.display(description="Team")
    def team_link(self, cohort: Cohort):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[cohort.team.pk]),
            cohort.team.name,
        )

    @admin.action(description="Recalculate selected cohorts")
    def recalculate_cohorts(self, request, queryset):
        """Admin action to recalculate selected cohorts"""
        successful_count = 0
        failed_count = 0
        skipped_count = 0

        for cohort in queryset:
            try:
                validate_cohort_for_recalculation(cohort, force=False)
                increment_version_and_enqueue_calculate_cohort(cohort, initiating_user=request.user)
                successful_count += 1
            except CohortValidationError:
                skipped_count += 1
            except Exception as e:
                failed_count += 1
                messages.error(request, f"Failed to recalculate cohort {cohort.id} ({cohort.name}): {str(e)}")

        # Summary message
        total_selected = queryset.count()
        summary_parts = []

        if successful_count > 0:
            summary_parts.append(f"{successful_count} recalculated successfully")
        if failed_count > 0:
            summary_parts.append(f"{failed_count} failed")
        if skipped_count > 0:
            summary_parts.append(f"{skipped_count} skipped (static, deleted, or already calculating)")

        summary = f"Processed {total_selected} cohort(s): " + ", ".join(summary_parts)

        if failed_count == 0:
            messages.success(request, summary)
        else:
            messages.warning(request, summary)

    @admin.action(description="Reset stuck cohorts (clear calculating status)")
    def reset_stuck_cohorts(self, request, queryset):
        """Admin action to reset cohorts that are stuck in calculating state"""
        from django.utils import timezone

        from dateutil.relativedelta import relativedelta

        reset_count = 0

        # Only reset cohorts that have been calculating for more than 1 hour
        stuck_threshold = timezone.now() - relativedelta(hours=1)

        for cohort in queryset:
            if cohort.is_calculating and cohort.last_calculation and cohort.last_calculation <= stuck_threshold:
                cohort.is_calculating = False
                cohort.errors_calculating = F("errors_calculating") + 1
                cohort.last_error_at = timezone.now()
                cohort.save(update_fields=["is_calculating", "errors_calculating", "last_error_at"])
                reset_count += 1

        if reset_count > 0:
            messages.success(request, f"Reset {reset_count} stuck cohort(s)")
        else:
            messages.info(request, "No stuck cohorts found to reset")
