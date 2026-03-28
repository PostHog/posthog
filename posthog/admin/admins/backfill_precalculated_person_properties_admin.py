from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.shortcuts import redirect, render


class BackfillPrecalculatedPersonPropertiesForm(forms.Form):
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
    batch_size = forms.IntegerField(
        initial=1000,
        min_value=100,
        help_text="Number of persons to process per batch using cursor-based pagination",
        label="Batch size",
    )


def backfill_precalculated_person_properties_view(request):
    """
    Custom admin view for backfilling precalculated_person_properties table.
    No model needed - just a form that triggers a management command.
    """
    if not request.user.is_staff:
        raise PermissionDenied

    if request.method == "POST":
        form = BackfillPrecalculatedPersonPropertiesForm(request.POST)
        if form.is_valid():
            command_args = []
            command_args.extend(["--team-id", str(form.cleaned_data["team_id"])])

            # Only add cohort_id if provided
            if form.cleaned_data.get("cohort_id"):
                command_args.extend(["--cohort-id", str(form.cleaned_data["cohort_id"])])

            command_args.extend(["--batch-size", str(form.cleaned_data["batch_size"])])

            try:
                call_command("backfill_precalculated_person_properties", *command_args)

                cohort_info = (
                    f"cohort {form.cleaned_data['cohort_id']}"
                    if form.cleaned_data.get("cohort_id")
                    else "all realtime cohorts"
                )
                messages.success(
                    request,
                    f"Backfill started successfully for {cohort_info} "
                    f"(team {form.cleaned_data['team_id']}) "
                    f"using cursor-based pagination with {form.cleaned_data['batch_size']} persons per batch. "
                    f"The workflow processes persons sequentially to avoid memory issues. "
                    f"Check Temporal UI for progress.",
                )
            except Exception as e:
                messages.error(request, f"Failed to start backfill: {str(e)}")

            return redirect("backfill-precalculated-person-properties")
    else:
        form = BackfillPrecalculatedPersonPropertiesForm()

    context = {
        "form": form,
        "title": "Backfill Precalculated Person Properties",
        "has_view_permission": True,
        "site_title": admin.site.site_title,
        "site_header": admin.site.site_header,
        "site_url": admin.site.site_url,
        "has_permission": True,
    }
    return render(request, "admin/backfill_precalculated_person_properties.html", context)
