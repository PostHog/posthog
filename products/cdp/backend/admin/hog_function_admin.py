from datetime import timedelta
from io import StringIO

from django import forms
from django.contrib import admin, messages
from django.core.management import call_command
from django.shortcuts import render
from django.urls import path, reverse
from django.utils.html import format_html

from posthog.management.commands.rerun_google_ads_failed_invocations import MAX_WINDOW_DAYS

from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionState


class HogFunctionAdminForm(forms.ModelForm):
    state = forms.ChoiceField(choices=[], required=False)  # Initially empty

    class Meta:
        model = HogFunction
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance: HogFunction = kwargs["instance"]
        self.fields["state"].choices = [(ex.value, ex.name) for ex in HogFunctionState]  # type: ignore
        self.fields["state"].initial = instance.status["state"]


class RerunGoogleAdsFailedInvocationsForm(forms.Form):
    """Admin-facing wrapper around the `rerun_google_ads_failed_invocations`
    management command. Mirrors its CLI flags one-for-one so a follow-up rerun
    from the shell produces the same result."""

    window_start = forms.DateTimeField(
        help_text="Inclusive lower bound on invocation scheduled_at (UTC). E.g. 2026-07-02 00:00:00.",
    )
    window_end = forms.DateTimeField(
        help_text="Exclusive upper bound (max 30d window — matches the ClickHouse TTL on hog_invocation_results).",
    )
    error_kinds = forms.CharField(
        required=False,
        initial="http_4xx",
        help_text="Comma-separated. Defaults to http_4xx.",
    )
    max_count = forms.IntegerField(
        required=False,
        min_value=1,
        help_text="Optional per-function cap. Server-side hard cap still applies.",
    )
    team_ids = forms.CharField(
        required=False,
        help_text="Optional comma-separated team IDs to restrict the run.",
    )
    dry_run = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Preview which hog functions would be targeted, without firing rerun requests.",
    )

    def clean_error_kinds(self) -> list[str]:
        raw = self.cleaned_data.get("error_kinds", "") or ""
        parts = [part.strip() for part in raw.split(",") if part.strip()]
        return parts or ["http_4xx"]

    def clean_team_ids(self) -> list[int]:
        raw = self.cleaned_data.get("team_ids", "") or ""
        if not raw.strip():
            return []
        try:
            return [int(part.strip()) for part in raw.split(",") if part.strip()]
        except ValueError:
            raise forms.ValidationError("Team IDs must be a comma-separated list of integers.")

    def clean(self):
        cleaned = super().clean() or {}
        start = cleaned.get("window_start")
        end = cleaned.get("window_end")
        if start and end:
            if end <= start:
                raise forms.ValidationError("window_end must be after window_start.")
            if end - start > timedelta(days=MAX_WINDOW_DAYS):
                span_days = (end - start).days
                raise forms.ValidationError(
                    f"Window cannot exceed {MAX_WINDOW_DAYS} days "
                    f"(ClickHouse TTL on hog_invocation_results). Got {span_days} days."
                )
        return cleaned


@admin.register(HogFunction)
class HogFunctionAdmin(admin.ModelAdmin):
    form = HogFunctionAdminForm
    change_list_template = "admin/cdp/hogfunction/change_list.html"
    list_select_related = ("team",)
    list_display = ("id", "name", "enabled")
    list_filter = (
        ("enabled", admin.BooleanFieldListFilter),
        ("deleted", admin.BooleanFieldListFilter),
        ("updated_at", admin.DateFieldListFilter),
    )
    list_select_related = ("team",)
    search_fields = ("team__name", "team__organization__name")
    ordering = ("-created_at",)
    readonly_fields = (
        "inputs",
        "inputs_schema",
        "filters",
        "bytecode",
        "hog",
        "team",
        "created_by",
        "team_link",
    )
    fields = (
        "name",
        "description",
        "enabled",
        "deleted",
        "state",
        "created_by",
        "icon_url",
        "hog",
        "bytecode",
        "inputs_schema",
        "inputs",
        "filters",
        "template_id",
    )

    @admin.display(description="Team")
    def team_link(self, hog_function):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[hog_function.team.pk]),
            hog_function.team.name,
        )

    def save_model(self, request, obj: HogFunction, form, change):
        super().save_model(request, obj, form, change)
        # Make an API request if 'state' is set
        if "state" in form.changed_data:
            state = int(form.cleaned_data["state"])
            obj.set_function_status(state)

    def get_urls(self):
        custom_urls = [
            path(
                "rerun-google-ads-failed-invocations/",
                self.admin_site.admin_view(self.rerun_google_ads_view),
                name="rerun-google-ads-failed-invocations",
            ),
        ]
        return custom_urls + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_rerun_google_ads_button"] = True
        return super().changelist_view(request, extra_context=extra_context)

    def rerun_google_ads_view(self, request):
        output: str | None = None
        if request.method == "POST":
            form = RerunGoogleAdsFailedInvocationsForm(request.POST)
            if form.is_valid():
                args = [
                    f"--window-start={form.cleaned_data['window_start'].isoformat()}",
                    f"--window-end={form.cleaned_data['window_end'].isoformat()}",
                ]
                for kind in form.cleaned_data["error_kinds"]:
                    args.append(f"--error-kind={kind}")
                if form.cleaned_data.get("max_count") is not None:
                    args.append(f"--max-count={form.cleaned_data['max_count']}")
                team_ids = form.cleaned_data["team_ids"]
                if team_ids:
                    args += ["--team-ids", *[str(t) for t in team_ids]]
                if form.cleaned_data["dry_run"]:
                    args.append("--dry-run")

                buf = StringIO()
                try:
                    call_command("rerun_google_ads_failed_invocations", *args, stdout=buf, stderr=buf)
                except Exception as e:
                    buf.write(f"\nCommand raised: {e!r}")
                    messages.error(request, "Command raised an exception; see output below.")
                else:
                    if form.cleaned_data["dry_run"]:
                        messages.info(request, "Dry run complete — no rerun requests were sent.")
                    else:
                        messages.success(request, "Rerun run complete. Check the output for per-function results.")
                output = buf.getvalue()
        else:
            form = RerunGoogleAdsFailedInvocationsForm()

        return render(
            request,
            "admin/cdp/hogfunction/rerun_google_ads.html",
            {"form": form, "output": output, "title": "Rerun Google Ads failed invocations"},
        )
