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
        help_text="Number of persons to process per batch using ID-range based batching",
        label="Batch size",
    )
    concurrent_workflows = forms.IntegerField(
        initial=5,
        min_value=1,
        max_value=100,
        help_text="Number of concurrent child workflows to run (1-100, default: 5)",
        label="Concurrent workflows",
    )
    person_id = forms.UUIDField(
        required=False,
        help_text="Optional: Specific person ID (UUID) to filter the backfill for. If provided, only processes properties for this person",
        label="Person ID",
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
            command_args.extend(["--concurrent-workflows", str(form.cleaned_data["concurrent_workflows"])])

            # Only add person_id if provided
            if form.cleaned_data.get("person_id"):
                command_args.extend(["--person-id", str(form.cleaned_data["person_id"])])

            try:
                call_command("backfill_precalculated_person_properties", *command_args)

                cohort_info = (
                    f"cohort {form.cleaned_data['cohort_id']}"
                    if form.cleaned_data.get("cohort_id")
                    else "all realtime cohorts"
                )
                person_info = (
                    f" (filtered to person {form.cleaned_data['person_id']})"
                    if form.cleaned_data.get("person_id")
                    else ""
                )
                messages.success(
                    request,
                    f"Backfill started successfully for {cohort_info}{person_info} "
                    f"(team {form.cleaned_data['team_id']}) "
                    f"using ID-range based batching with {form.cleaned_data['batch_size']} persons per batch "
                    f"and {form.cleaned_data['concurrent_workflows']} concurrent workflows. "
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
