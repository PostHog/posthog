from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.shortcuts import redirect, render


class BackfillPrecalculatedEventsForm(forms.Form):
    team_id = forms.IntegerField(
        min_value=1,
        help_text="Team ID for the cohort",
        label="Team ID",
    )
    cohort_id = forms.IntegerField(
        required=False,
        help_text="Optional: Specific cohort ID to backfill. If not provided, backfills all realtime cohorts for the team",
        label="Cohort ID",
    )
    days = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=90,
        help_text="Override the backfill time window in days (default: auto-computed from filters, max: 90)",
        label="Days to backfill",
    )
    concurrent_workflows = forms.IntegerField(
        required=False,
        initial=5,
        min_value=1,
        max_value=100,
        help_text="Number of concurrent child workflows to run (1-100, default: 5)",
        label="Concurrent workflows",
    )

    def clean_concurrent_workflows(self):
        value = self.cleaned_data.get("concurrent_workflows")
        if value is None:
            return 5
        return value


def backfill_precalculated_events_view(request):
    """Custom admin view for backfilling precalculated_events table."""
    if not request.user.is_staff:
        raise PermissionDenied

    if request.method == "POST":
        form = BackfillPrecalculatedEventsForm(request.POST)
        if form.is_valid():
            command_args = []
            command_args.extend(["--team-id", str(form.cleaned_data["team_id"])])

            if form.cleaned_data.get("cohort_id"):
                command_args.extend(["--cohort-id", str(form.cleaned_data["cohort_id"])])

            if form.cleaned_data.get("days"):
                command_args.extend(["--days", str(form.cleaned_data["days"])])

            command_args.extend(["--concurrent-workflows", str(form.cleaned_data["concurrent_workflows"])])

            try:
                call_command("backfill_precalculated_events", *command_args)

                cohort_info = (
                    f"cohort {form.cleaned_data['cohort_id']}"
                    if form.cleaned_data.get("cohort_id")
                    else "all realtime cohorts"
                )
                days_info = (
                    f" for {form.cleaned_data['days']} days"
                    if form.cleaned_data.get("days")
                    else " (auto-computed window)"
                )
                messages.success(
                    request,
                    f"Event backfill started successfully for {cohort_info}{days_info} "
                    f"(team {form.cleaned_data['team_id']}) "
                    f"with {form.cleaned_data['concurrent_workflows']} concurrent workflows. "
                    f"Check Temporal UI for progress.",
                )
            except Exception as e:
                messages.error(request, f"Failed to start backfill: {str(e)}")

            return redirect("backfill-precalculated-events")
    else:
        form = BackfillPrecalculatedEventsForm()

    context = {
        "form": form,
        "title": "Backfill Precalculated Events",
        "has_view_permission": True,
        "site_title": admin.site.site_title,
        "site_header": admin.site.site_header,
        "site_url": admin.site.site_url,
        "has_permission": True,
    }
    return render(request, "admin/backfill_precalculated_events.html", context)
