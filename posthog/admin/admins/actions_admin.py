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
        help_text="Number of parallel child workflows to spawn",
        label="Parallelism",
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

            try:
                call_command("analyze_actions", *command_args)

                messages.success(
                    request,
                    f"Actions analysis started successfully with {form.cleaned_data['parallelism']} parallel workers. "
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
