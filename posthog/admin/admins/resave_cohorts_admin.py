from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.shortcuts import redirect, render

from posthog.management.commands.resave_cohorts import UnclassifiedCohortsError


class ResaveCohortsForm(forms.Form):
    team_id = forms.IntegerField(required=False, help_text="Only process cohorts for this team id (optional)")
    batch_size = forms.IntegerField(initial=500, min_value=1, max_value=5000, help_text="Cohorts per batch")
    dry_run = forms.BooleanField(initial=True, required=False, help_text="Do not save, only report summary")


def resave_cohorts_view(request):
    """
    Admin view to trigger cohort re-save to regenerate compiled bytecode and cohort_type.
    Delegates to the `resave_cohorts` management command.
    """
    if not request.user.is_staff:
        raise PermissionDenied

    if request.method == "POST":
        form = ResaveCohortsForm(request.POST)
        if form.is_valid():
            command_kwargs = {
                "batch_size": form.cleaned_data["batch_size"],
                "dry_run": form.cleaned_data["dry_run"],
            }
            team_id = form.cleaned_data.get("team_id")
            if team_id is not None:
                # Presence, not truthiness: team 0 has to reach the command, which rejects it. Reading
                # it as "no team given" would silently widen the run to every team.
                # `call_command` skips argparse coercion for keyword options, so the list the
                # `--team-id` flag builds has to be passed already built.
                command_kwargs["team_id"] = [team_id]

            try:
                call_command("resave_cohorts", **command_kwargs)
                scope = f"team {team_id}" if team_id is not None else "all teams"
                mode = "dry-run" if form.cleaned_data["dry_run"] else "apply"
                messages.success(
                    request,
                    f"Cohort re-save started ({mode}) for {scope} with batch_size={form.cleaned_data['batch_size']}.",
                )
            except UnclassifiedCohortsError as e:
                # The run finished and persisted its saves, so this is not a failure to start.
                messages.warning(request, f"Cohort re-save finished, but found unclassified cohorts: {str(e)}")
            except Exception as e:
                messages.error(request, f"Failed to start cohort re-save: {str(e)}")

            return redirect("resave-cohorts")
    else:
        form = ResaveCohortsForm()

    context = {
        "form": form,
        "title": "Resave Cohorts (Regenerate Bytecode & Type)",
        "has_view_permission": True,
        "site_title": admin.site.site_title,
        "site_header": admin.site.site_header,
        "site_url": admin.site.site_url,
        "has_permission": True,
    }
    return render(request, "admin/resave_cohorts.html", context)
