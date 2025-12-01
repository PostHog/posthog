import math

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.shortcuts import redirect, render


class BackfillPrecalculatedPersonPropertiesForm(forms.Form):
    cohort_id = forms.IntegerField(
        min_value=1,
        help_text="Cohort ID to backfill person properties for",
        label="Cohort ID",
    )
    team_id = forms.IntegerField(
        min_value=1,
        help_text="Team ID for the cohort",
        label="Team ID",
    )
    parallelism = forms.IntegerField(
        initial=5,
        min_value=1,
        max_value=50,
        help_text="Number of parallel child workflows to spawn",
        label="Parallelism",
    )
    batch_size = forms.IntegerField(
        initial=1000,
        min_value=100,
        max_value=10000,
        help_text="Number of persons to process per batch within each worker",
        label="Batch size",
    )
    workflows_per_batch = forms.IntegerField(
        initial=10,
        min_value=1,
        max_value=20,
        help_text="Number of workflows to start per batch for jittered scheduling",
        label="Workflows per batch",
    )
    batch_delay_minutes = forms.IntegerField(
        initial=1,
        min_value=1,
        max_value=60,
        help_text="Delay between batches in minutes",
        label="Batch delay (minutes)",
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
            command_args.extend(["--cohort-id", str(form.cleaned_data["cohort_id"])])
            command_args.extend(["--team-id", str(form.cleaned_data["team_id"])])
            command_args.extend(["--parallelism", str(form.cleaned_data["parallelism"])])
            command_args.extend(["--batch-size", str(form.cleaned_data["batch_size"])])
            command_args.extend(["--workflows-per-batch", str(form.cleaned_data["workflows_per_batch"])])
            command_args.extend(["--batch-delay-minutes", str(form.cleaned_data["batch_delay_minutes"])])

            try:
                call_command("backfill_precalculated_person_properties", *command_args)

                total_batches = math.ceil(form.cleaned_data["parallelism"] / form.cleaned_data["workflows_per_batch"])
                total_time_minutes = (total_batches - 1) * form.cleaned_data["batch_delay_minutes"]

                messages.success(
                    request,
                    f"Backfill started successfully for cohort {form.cleaned_data['cohort_id']} "
                    f"with {form.cleaned_data['parallelism']} workflows "
                    f"in {total_batches} batches ({form.cleaned_data['workflows_per_batch']} per batch, "
                    f"{form.cleaned_data['batch_delay_minutes']}min delays). "
                    f"All workflows will be scheduled over ~{total_time_minutes} minutes. "
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
