import math

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.shortcuts import redirect, render


class RealtimeCohortCalculationForm(forms.Form):
    days = forms.IntegerField(initial=30, min_value=1, help_text="Number of days to look back", label="Days Lookback")
    min_matches = forms.IntegerField(
        initial=3, min_value=1, help_text="Minimum number of matches required", label="Minimum Matches"
    )
    parallelism = forms.IntegerField(
        initial=10,
        min_value=1,
        max_value=50,
        help_text="Number of parallel child workflows to spawn",
        label="Parallelism",
    )
    workflows_per_batch = forms.IntegerField(
        initial=5,
        min_value=1,
        max_value=20,
        help_text="Number of workflows to start per batch for jittered scheduling",
        label="Workflows per batch",
    )
    batch_delay_minutes = forms.IntegerField(
        initial=5,
        min_value=1,
        max_value=60,
        help_text="Delay between batches in minutes",
        label="Batch delay (minutes)",
    )


def analyze_realtime_cohort_calculation_view(request):
    """
    Custom admin view for realtime cohort calculation.
    No model needed - just a form that triggers a management command.
    """
    if not request.user.is_staff:
        raise PermissionDenied

    if request.method == "POST":
        form = RealtimeCohortCalculationForm(request.POST)
        if form.is_valid():
            command_args = []
            command_args.extend(["--days", str(form.cleaned_data["days"])])
            command_args.extend(["--min-matches", str(form.cleaned_data["min_matches"])])
            command_args.extend(["--parallelism", str(form.cleaned_data["parallelism"])])
            command_args.extend(["--workflows-per-batch", str(form.cleaned_data["workflows_per_batch"])])
            command_args.extend(["--batch-delay-minutes", str(form.cleaned_data["batch_delay_minutes"])])

            try:
                call_command("analyze_realtime_cohort_calculation", *command_args)

                total_batches = math.ceil(form.cleaned_data["parallelism"] / form.cleaned_data["workflows_per_batch"])
                total_time_minutes = (total_batches - 1) * form.cleaned_data["batch_delay_minutes"]

                messages.success(
                    request,
                    f"Realtime cohort calculation started successfully with {form.cleaned_data['parallelism']} workflows "
                    f"in {total_batches} batches ({form.cleaned_data['workflows_per_batch']} per batch, "
                    f"{form.cleaned_data['batch_delay_minutes']}min delays). "
                    f"All workflows will be scheduled over ~{total_time_minutes} minutes. "
                    f"Check Temporal UI for progress.",
                )
            except Exception as e:
                messages.error(request, f"Failed to start realtime cohort calculation: {str(e)}")

            return redirect("realtime-cohorts-calculation")
    else:
        form = RealtimeCohortCalculationForm()

    context = {
        "form": form,
        "title": "Realtime Cohort Calculation",
        "has_view_permission": True,
        "site_title": admin.site.site_title,
        "site_header": admin.site.site_header,
        "site_url": admin.site.site_url,
        "has_permission": True,
    }
    return render(request, "admin/realtime_cohort_calculation.html", context)
