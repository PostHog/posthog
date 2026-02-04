from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from posthog.models import Cohort
from posthog.models.cohort.util import CohortValidationError, validate_cohort_for_recalculation
from posthog.tasks.calculate_cohort import increment_version_and_enqueue_calculate_cohort


class RecalculateCohortForm(forms.Form):
    cohort_id = forms.IntegerField(help_text="Cohort ID to recalculate")
    force = forms.BooleanField(
        initial=False, required=False, help_text="Force recalculation even if cohort is currently calculating"
    )


def recalculate_cohort_view(request):
    """
    Admin view to trigger cohort recalculation.
    Delegates to the cohort calculation tasks.
    """
    if not request.user.is_staff:
        raise PermissionDenied

    if request.method == "POST":
        form = RecalculateCohortForm(request.POST)
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

                messages.success(request, f"Successfully enqueued recalculation for cohort {cohort_id} ({cohort.name})")
            except Exception as e:
                messages.error(request, f"Failed to recalculate cohort {cohort_id}: {str(e)}")

            return redirect("recalculate-cohort")
    else:
        form = RecalculateCohortForm()

    context = {
        "form": form,
        "title": "Recalculate Cohort",
        "has_view_permission": True,
        "site_title": admin.site.site_title,
        "site_header": admin.site.site_header,
        "site_url": admin.site.site_url,
        "has_permission": True,
    }
    return render(request, "admin/recalculate_cohort.html", context)
