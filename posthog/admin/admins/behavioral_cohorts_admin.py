from django import forms
from django.contrib import admin, messages
from django.core.management import call_command
from django.db import models
from django.shortcuts import redirect, render
from django.urls import path, reverse


class BehavioralCohortAnalysisForm(forms.Form):
    min_matches = forms.IntegerField(
        initial=3, min_value=1, help_text="Minimum number of matches required", label="Minimum Matches"
    )
    days = forms.IntegerField(initial=30, min_value=1, help_text="Number of days to look back", label="Days Lookback")
    team_id = forms.IntegerField(required=False, help_text="Optional: Filter to a specific team ID", label="Team ID")
    cohort_id = forms.IntegerField(
        required=False, help_text="Optional: Filter to a specific cohort ID", label="Cohort ID"
    )
    condition = forms.CharField(
        required=False,
        max_length=255,
        help_text="Optional: Filter to a specific condition hash",
        label="Condition Hash",
    )
    parallelism = forms.IntegerField(
        initial=10,
        min_value=1,
        max_value=50,
        help_text="Number of parallel child workflows to spawn",
        label="Parallelism",
    )
    schedule = forms.BooleanField(
        required=False,
        help_text="Schedule the workflow to run periodically instead of running once",
        label="Schedule Periodic Run",
    )
    duration = forms.IntegerField(
        initial=60,
        min_value=1,
        help_text="Duration in minutes to run the schedule (only with schedule enabled)",
        label="Schedule Duration (minutes)",
    )
    interval = forms.IntegerField(
        initial=5,
        min_value=1,
        help_text="Interval in minutes between runs (only with schedule enabled)",
        label="Schedule Interval (minutes)",
    )


class BehavioralCohortAnalysis(models.Model):
    """
    Proxy model to create a separate admin interface for behavioral cohort analysis.
    This doesn't create a new database table, just provides an admin interface.
    """

    class Meta:
        managed = False
        verbose_name = "Behavioral Cohort Analysis"
        verbose_name_plural = "Behavioral Cohort Analysis"


class BehavioralCohortAnalysisAdmin(admin.ModelAdmin):
    """
    Admin interface for running behavioral cohort analysis.
    This provides a dedicated interface to trigger the analyze_behavioral_cohorts management command.
    """

    def has_add_permission(self, request):
        # Disable the "Add" button since this is just for running analysis
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Redirect directly to the analysis form
        return redirect(reverse("admin:behavioral-cohort-analysis"))

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "",
                self.admin_site.admin_view(self.analyze_behavioral_cohorts_view),
                name="behavioral-cohort-analysis",
            ),
        ]
        return custom_urls + urls

    def analyze_behavioral_cohorts_view(self, request):
        if request.method == "POST":
            form = BehavioralCohortAnalysisForm(request.POST)
            if form.is_valid():
                # Build command arguments
                command_args = []

                command_args.extend(["--min-matches", str(form.cleaned_data["min_matches"])])
                command_args.extend(["--days", str(form.cleaned_data["days"])])
                command_args.extend(["--parallelism", str(form.cleaned_data["parallelism"])])

                if form.cleaned_data.get("team_id"):
                    command_args.extend(["--team-id", str(form.cleaned_data["team_id"])])
                if form.cleaned_data.get("cohort_id"):
                    command_args.extend(["--cohort-id", str(form.cleaned_data["cohort_id"])])
                if form.cleaned_data.get("condition"):
                    command_args.extend(["--condition", form.cleaned_data["condition"]])

                if form.cleaned_data.get("schedule"):
                    command_args.append("--schedule")
                    command_args.extend(["--duration", str(form.cleaned_data["duration"])])
                    command_args.extend(["--interval", str(form.cleaned_data["interval"])])

                try:
                    # Run the management command
                    call_command("analyze_behavioral_cohorts", *command_args)

                    if form.cleaned_data.get("schedule"):
                        messages.success(
                            request,
                            f"Behavioral cohorts analysis scheduled successfully. "
                            f"It will run every {form.cleaned_data['interval']} minutes "
                            f"for {form.cleaned_data['duration']} minutes.",
                        )
                    else:
                        messages.success(
                            request,
                            f"Behavioral cohorts analysis started successfully with {form.cleaned_data['parallelism']} parallel workers. "
                            f"Check Temporal UI for progress.",
                        )
                except Exception as e:
                    messages.error(request, f"Failed to start behavioral cohorts analysis: {str(e)}")

                # Stay on the same page after submission
                return redirect(request.path)
        else:
            form = BehavioralCohortAnalysisForm()

        context = {
            "form": form,
            "title": "Behavioral Cohort Analysis",
            "opts": self.model._meta,
            "has_view_permission": True,
            "site_title": "PostHog Admin",
            "site_header": "PostHog Admin",
        }
        return render(request, "admin/behavioral_cohort_analysis.html", context)
