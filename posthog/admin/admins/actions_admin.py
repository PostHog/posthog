from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.shortcuts import redirect, render


class ActionsAnalysisForm(forms.Form):
    days = forms.IntegerField(initial=30, min_value=1, help_text="Number of days to look back", label="Days Lookback")
    min_matches = forms.IntegerField(
        initial=3, min_value=1, help_text="Minimum number of matches required", label="Minimum Matches"
    )
    parallelism = forms.IntegerField(
        initial=10,
        min_value=1,
        max_value=50,
        help_text="Legacy parameter - no longer used (each action gets its own workflow)",
        label="Parallelism (Legacy)",
    )
    batch_size = forms.IntegerField(
        initial=1000,
        min_value=1,
        max_value=5000,
        help_text="Number of workflows to start per batch to avoid spikes",
        label="Batch Size",
    )
    batch_delay = forms.IntegerField(
        initial=60,
        min_value=0,
        max_value=3600,
        help_text="Delay between batches in seconds",
        label="Batch Delay (seconds)",
    )
    max_actions = forms.IntegerField(
        initial=0,
        min_value=0,
        help_text="Maximum number of actions to process, 0 for all actions",
        label="Max Actions (0 = all)",
    )


def analyze_actions_view(request):
    """
    Custom admin view for actions analysis.
    No model needed - just a form that triggers a management command.
    """
    if not request.user.is_staff:
        raise PermissionDenied

    if request.method == "POST":
        form = ActionsAnalysisForm(request.POST)
        if form.is_valid():
            command_args = []
            command_args.extend(["--days", str(form.cleaned_data["days"])])
            command_args.extend(["--min-matches", str(form.cleaned_data["min_matches"])])
            command_args.extend(["--parallelism", str(form.cleaned_data["parallelism"])])
            command_args.extend(["--batch-size", str(form.cleaned_data["batch_size"])])
            command_args.extend(["--batch-delay", str(form.cleaned_data["batch_delay"])])
            command_args.extend(["--max-actions", str(form.cleaned_data["max_actions"])])

            try:
                call_command("analyze_actions", *command_args)

                action_count_msg = (
                    f"up to {form.cleaned_data['max_actions']} actions"
                    if form.cleaned_data["max_actions"] > 0
                    else "all actions"
                )

                messages.success(
                    request,
                    f"Actions analysis started successfully for {action_count_msg} "
                    f"in batches of {form.cleaned_data['batch_size']} with {form.cleaned_data['batch_delay']}s delays. "
                    f"Check Temporal UI for progress.",
                )
            except Exception as e:
                messages.error(request, f"Failed to start actions analysis: {str(e)}")

            return redirect("actions-analysis")
    else:
        form = ActionsAnalysisForm()

    context = {
        "form": form,
        "title": "Actions Analysis",
        "has_view_permission": True,
        "site_title": admin.site.site_title,
        "site_header": admin.site.site_header,
        "site_url": admin.site.site_url,
        "has_permission": True,
    }
    return render(request, "admin/actions_analysis.html", context)
