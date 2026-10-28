import json
from datetime import UTC, datetime, timedelta
from typing import Any

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from posthog.exceptions_capture import capture_exception

from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionState
from products.cdp.backend.presentation.hog_invocations.rerun import RERUN_MAX_WINDOW_DAYS
from products.cdp.backend.services.invocation_replay import (
    DEFAULT_LATEST_PER_PERSON_TEMPLATE_IDS,
    SKIP_REASON_LABELS,
    ReplayCriteria,
    ReplayOverlapError,
    can_release_replay,
    claim_replay,
    get_replay_state,
    mark_replay_dispatch_unknown,
    plan_replay,
    release_replay_claim,
)
from products.cdp.backend.tasks.invocation_replay import run_invocation_replay

REPLAY_TEMPLATE = "admin/cdp/hogfunction/replay_failed_invocations.html"

REPLAY_FIELD_GROUPS = (
    ("What failed", ("window_start", "window_end", "error_message_contains", "error_kinds")),
    (
        "Scope",
        ("include_workflows", "team_ids", "template_ids", "exclude_template_ids", "latest_per_person_template_ids"),
    ),
    ("Safety checks", ("require_success_since_window", "skip_already_rerun", "skip_failing_before_window")),
)


def _result_summary(result: dict[str, Any]) -> str:
    # A successful rerun call answers with the id of the job it queued. Anything
    # else is an error message, which the operator needs to read in full.
    if result["status_code"] == 200:
        try:
            return f"job {json.loads(result['detail'])['rerun_job_id']}"
        except (ValueError, KeyError, TypeError):
            pass
    return result["detail"]


def _split_list(raw: str) -> list[str]:
    return [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ReplayFailedInvocationsForm(forms.Form):
    window_start = forms.DateTimeField(help_text="UTC, inclusive. For example 2026-10-22 11:30:00.")
    window_end = forms.DateTimeField(
        help_text=f"UTC, exclusive. At most {RERUN_MAX_WINDOW_DAYS} days after the start, because older runs are deleted."
    )
    error_message_contains = forms.CharField(
        required=False,
        help_text='Only runs whose latest error contains this text, ignoring case. For example "401".',
    )
    error_kinds = forms.CharField(
        required=False,
        help_text="Comma-separated, for example http_4xx. Set this or the error text, or both.",
    )
    include_workflows = forms.BooleanField(
        required=False,
        label="Include workflows",
        help_text=(
            "Also replay workflow runs that stopped on a failed step. Each run continues from that step, "
            "so steps that already ran are not sent again."
        ),
    )
    team_ids = forms.CharField(required=False, help_text="Comma-separated. Leave empty for every team.")
    template_ids = forms.CharField(
        required=False,
        help_text=(
            "Comma-separated. Leave empty for every template, custom functions included. "
            "A workflow matches when one of its steps uses the template."
        ),
    )
    exclude_template_ids = forms.CharField(
        required=False,
        help_text="Comma-separated. Use for destinations where a late send is noise, like template-github.",
    )
    latest_per_person_template_ids = forms.CharField(
        required=False,
        initial=", ".join(DEFAULT_LATEST_PER_PERSON_TEMPLATE_IDS),
        help_text=(
            "Comma-separated templates that write a person's current state, like a CRM contact sync. For these, "
            "only the latest failed run per person is replayed, and not at all if a later run for that person succeeded."
        ),
    )
    require_success_since_window = forms.BooleanField(
        required=False,
        initial=True,
        label="Skip functions with no success since the window",
        help_text="A function that still fails, for example because its integration is disconnected, would only fail again.",
    )
    skip_already_rerun = forms.BooleanField(required=False, initial=True, label="Skip runs that were already re-run")
    skip_failing_before_window = forms.BooleanField(
        required=False,
        initial=True,
        label="Skip functions that already failed this way before the window",
        help_text="Looks at the day before the window. Those failures have a cause of their own, like a revoked key.",
    )

    def clean_team_ids(self) -> list[int]:
        try:
            return [int(part) for part in _split_list(self.cleaned_data.get("team_ids") or "")]
        except ValueError:
            raise forms.ValidationError("Team IDs must be whole numbers.")

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        start, end = cleaned.get("window_start"), cleaned.get("window_end")
        if start and end:
            start, end = _as_utc(start), _as_utc(end)
            cleaned["window_start"], cleaned["window_end"] = start, end
            if end <= start:
                raise forms.ValidationError("The window end must be after the window start.")
            if end - start > timedelta(days=RERUN_MAX_WINDOW_DAYS):
                raise forms.ValidationError(f"The window cannot be longer than {RERUN_MAX_WINDOW_DAYS} days.")
        if not (cleaned.get("error_message_contains") or "").strip() and not _split_list(
            cleaned.get("error_kinds") or ""
        ):
            raise forms.ValidationError(
                "Set the error text or the error kinds, so the replay only includes failures from the incident."
            )
        return cleaned

    def to_criteria(self) -> ReplayCriteria:
        data = self.cleaned_data
        return ReplayCriteria(
            window_start=data["window_start"],
            window_end=data["window_end"],
            error_message_contains=(data.get("error_message_contains") or "").strip(),
            error_kinds=tuple(_split_list(data.get("error_kinds") or "")),
            team_ids=tuple(data["team_ids"]),
            template_ids=tuple(_split_list(data.get("template_ids") or "")),
            exclude_template_ids=tuple(_split_list(data.get("exclude_template_ids") or "")),
            latest_per_person_template_ids=tuple(_split_list(data.get("latest_per_person_template_ids") or "")),
            require_success_since_window=bool(data.get("require_success_since_window")),
            skip_already_rerun=bool(data.get("skip_already_rerun")),
            skip_failing_before_window=bool(data.get("skip_failing_before_window")),
            include_workflows=bool(data.get("include_workflows")),
        )


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
                "replay-failed-invocations/",
                self.admin_site.admin_view(self.replay_failed_invocations_view),
                name="cdp-replay-failed-invocations",
            ),
            path(
                "replay-failed-invocations/<str:fingerprint>/",
                self.admin_site.admin_view(self.replay_status_view),
                name="cdp-replay-failed-invocations-status",
            ),
        ]
        return custom_urls + super().get_urls()

    def replay_failed_invocations_view(self, request: HttpRequest) -> HttpResponse:
        # Every step sends the form again and computes the plan again, so no step
        # acts on a plan held from an earlier request. The send step also checks
        # the fingerprint the operator reviewed, and refuses when the plan changed.
        if not self.has_change_permission(request):
            raise PermissionDenied
        context: dict[str, Any] = {**self.admin_site.each_context(request), "title": "Replay failed invocations"}

        def respond(step: str) -> HttpResponse:
            context["step"] = step
            if step == "form":
                form = context["form"]
                context["field_groups"] = [
                    (title, [form[name] for name in names]) for title, names in REPLAY_FIELD_GROUPS
                ]
            return render(request, REPLAY_TEMPLATE, context)

        if request.method != "POST":
            context["form"] = ReplayFailedInvocationsForm()
            return respond("form")

        form = ReplayFailedInvocationsForm(request.POST)
        context["form"] = form
        if not form.is_valid() or request.POST.get("action") == "edit":
            return respond("form")

        plan = plan_replay(form.to_criteria())
        context["plan"] = plan
        context["skipped_rows"] = [(SKIP_REASON_LABELS[reason], count) for reason, count in plan.skipped.items()]
        context["function_rows"] = [
            {
                "function": function,
                "skipped": [(SKIP_REASON_LABELS[reason], count) for reason, count in function.skipped.items()],
            }
            for function in plan.functions
        ]

        action = request.POST.get("action", "preview")
        if action != "execute":
            return respond("details" if action == "details" else "summary")

        if request.POST.get("fingerprint") != plan.fingerprint:
            messages.error(request, "The runs changed since you reviewed them, so nothing was sent. Review them again.")
            return respond("details")
        if request.POST.get("confirm_count", "").strip() != str(plan.invocation_count):
            messages.error(request, f"Type {plan.invocation_count} to confirm. Nothing was sent.")
            return respond("details")
        if plan.invocation_count == 0:
            messages.info(request, "There is nothing to replay.")
            return respond("summary")

        actor = f"admin:{request.user.pk}"
        try:
            claimed = claim_replay(plan, actor=actor)
        except ReplayOverlapError as error:
            messages.error(request, f"{error} Nothing was sent.")
            return respond("details")
        if claimed is None:
            messages.warning(request, "This plan was already sent, so it was not sent again.")
        else:
            # The send runs in a task, because a plan can need hundreds of requests and
            # the admin request would time out before they finish.
            try:
                run_invocation_replay.delay(plan.criteria.to_payload(), plan.fingerprint, actor, claimed)
            except Exception as error:
                capture_exception(error)
                mark_replay_dispatch_unknown(plan.fingerprint)
        return redirect("admin:cdp-replay-failed-invocations-status", fingerprint=plan.fingerprint)

    def replay_status_view(self, request: HttpRequest, fingerprint: str) -> HttpResponse:
        if not self.has_change_permission(request):
            raise PermissionDenied
        state = get_replay_state(fingerprint)
        if request.method == "POST" and request.POST.get("action") == "release":
            if release_replay_claim(fingerprint, actor=f"admin:{request.user.pk}"):
                messages.success(request, "This plan can be sent again. Preview the same filters to send it.")
            else:
                messages.error(request, "This plan is still being sent, so it cannot be released yet.")
            return redirect("admin:cdp-replay-failed-invocations-status", fingerprint=fingerprint)
        can_release = can_release_replay(fingerprint)
        results = (state or {}).get("results", [])
        context: dict[str, Any] = {
            **self.admin_site.each_context(request),
            "title": "Replay failed invocations",
            "step": "status",
            "fingerprint": fingerprint,
            "state": state,
            "can_release": can_release,
            "result_rows": [{**r, "failed": r["status_code"] != 200, "summary": _result_summary(r)} for r in results],
            "sent_requests": len(results),
            "failed_requests": sum(1 for r in results if r["status_code"] != 200),
        }
        return render(request, REPLAY_TEMPLATE, context)
