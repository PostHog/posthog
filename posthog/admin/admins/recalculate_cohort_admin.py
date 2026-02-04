from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import F
from django.shortcuts import redirect, render
from django.utils import timezone

from dateutil.relativedelta import relativedelta

from posthog.models import Cohort
from posthog.models.cohort.util import CohortValidationError, validate_cohort_for_recalculation
from posthog.tasks.calculate_cohort import increment_version_and_enqueue_calculate_cohort


class RecalculateCohortForm(forms.Form):
    cohort_id = forms.IntegerField(help_text="Cohort ID to recalculate")
    force = forms.BooleanField(
        initial=False, required=False, help_text="Force recalculation even if cohort is currently calculating"
    )


class ResetCohortForm(forms.Form):
    cohort_id = forms.IntegerField(help_text="Cohort ID to reset (removes calculating status)")
    force_reset = forms.BooleanField(
        initial=False, required=False, help_text="Reset cohort even if it was updated recently (within 1 hour)"
    )


def recalculate_cohort_view(request):
    """
    Admin view to trigger cohort recalculation and reset stuck cohorts.
    Delegates to the cohort calculation tasks.
    """
    if not request.user.is_staff:
        raise PermissionDenied

    if request.method == "POST":
        # Determine which form was submitted
        action = request.POST.get("action")

        if action == "recalculate":
            form = RecalculateCohortForm(request.POST)
            reset_form = ResetCohortForm()
            if form.is_valid():
                cohort_id = form.cleaned_data["cohort_id"]
                force = form.cleaned_data["force"]

                try:
                    cohort = Cohort.objects.get(pk=cohort_id)
                except Cohort.DoesNotExist:
                    messages.error(request, f"Cohort with ID {cohort_id} does not exist")
                    return redirect("recalculate-cohort")

                try:
                    validate_cohort_for_recalculation(cohort, force=force)
                except CohortValidationError as e:
                    messages.error(request, str(e))
                    return redirect("recalculate-cohort")

                try:
                    # Force reset if needed
                    if force and cohort.is_calculating:
                        cohort.is_calculating = False
                        cohort.save(update_fields=["is_calculating"])
                        messages.warning(request, f"Forced reset of calculating status for cohort {cohort_id}")

                    # Recalculate - this will enqueue the calculation automatically
                    increment_version_and_enqueue_calculate_cohort(cohort, initiating_user=request.user)

                    messages.success(
                        request, f"Successfully enqueued recalculation for cohort {cohort_id} ({cohort.name})"
                    )
                except Exception as e:
                    messages.error(request, f"Failed to recalculate cohort {cohort_id}: {str(e)}")

                return redirect("recalculate-cohort")

        elif action == "reset":
            reset_form = ResetCohortForm(request.POST)
            form = RecalculateCohortForm()
            if reset_form.is_valid():
                cohort_id = reset_form.cleaned_data["cohort_id"]
                force_reset = reset_form.cleaned_data["force_reset"]

                try:
                    cohort = Cohort.objects.get(pk=cohort_id)
                except Cohort.DoesNotExist:
                    messages.error(request, f"Cohort with ID {cohort_id} does not exist")
                    return redirect("recalculate-cohort")

                try:
                    # Check if cohort is actually stuck or if we should force reset
                    if cohort.is_calculating:
                        should_reset = force_reset

                        if not force_reset and cohort.last_calculation:
                            # Only reset if cohort has been calculating for more than 1 hour
                            stuck_threshold = timezone.now() - relativedelta(hours=1)
                            should_reset = cohort.last_calculation <= stuck_threshold
                        elif not force_reset:
                            # No last_calculation time, assume it's stuck
                            should_reset = True

                        if should_reset:
                            cohort.is_calculating = False
                            cohort.errors_calculating = F("errors_calculating") + 1
                            cohort.last_error_at = timezone.now()
                            cohort.save(update_fields=["is_calculating", "errors_calculating", "last_error_at"])
                            messages.success(request, f"Successfully reset stuck cohort {cohort_id} ({cohort.name})")
                        else:
                            messages.warning(
                                request,
                                f"Cohort {cohort_id} was updated recently and may not be stuck. Use 'Force reset' if needed.",
                            )
                    else:
                        messages.info(request, f"Cohort {cohort_id} is not currently calculating")
                except Exception as e:
                    messages.error(request, f"Failed to reset cohort {cohort_id}: {str(e)}")

                return redirect("recalculate-cohort")
    else:
        form = RecalculateCohortForm()
        reset_form = ResetCohortForm()

    context = {
        "form": form,
        "reset_form": reset_form,
        "title": "Cohort Management",
        "has_view_permission": True,
        "site_title": admin.site.site_title,
        "site_header": admin.site.site_header,
        "site_url": admin.site.site_url,
        "has_permission": True,
    }
    return render(request, "admin/recalculate_cohort.html", context)
