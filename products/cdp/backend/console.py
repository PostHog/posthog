import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import redirect
from django.urls import reverse

import structlog

from posthog.admin.console.panels import Owner, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import (
    Block,
    Cell,
    ConsoleTool,
    FieldGroup,
    Filters,
    Link,
    Links,
    Live,
    Notice,
    Page,
    Row,
    Stat,
    Stats,
    Table,
    ToolOperation,
)
from posthog.exceptions_capture import capture_exception

from products.cdp.backend.presentation.hog_invocations.rerun import RERUN_MAX_WINDOW_DAYS
from products.cdp.backend.services.invocation_replay import (
    DEFAULT_LATEST_PER_PERSON_TEMPLATE_IDS,
    SKIP_REASON_LABELS,
    WORKFLOWS_TEMPLATE_KEY,
    ReplayCriteria,
    ReplayOverlapError,
    ReplayPlan,
    can_release_replay,
    get_replay_state,
    plan_replay,
    release_replay_claim,
)
from products.cdp.backend.tasks.invocation_replay import dispatch_invocation_replay

logger = structlog.get_logger(__name__)

WORKFLOWS = Owner(name="Workflows", crest="workflows")
TOOL_KEY = "replay-failed-runs"
FILTER_GROUPS = (
    FieldGroup(
        title="What failed", field_names=("window_start", "window_end", "error_message_contains", "error_kinds")
    ),
    FieldGroup(
        title="Scope",
        field_names=(
            "include_workflows",
            "team_ids",
            "template_ids",
            "exclude_template_ids",
            "latest_per_person_template_ids",
        ),
    ),
    FieldGroup(
        title="Safety checks",
        field_names=("require_success_since_window", "skip_already_rerun", "skip_failing_before_window"),
    ),
)
PLANNING_LABEL = "Finding runs. This can take a minute..."
STATUS_LABELS: dict[str, tuple[str, Tone]] = {
    "queued": ("Queued", Tone.WARNING),
    "running": ("Sending", Tone.WARNING),
    "done": ("Done", Tone.SUCCESS),
    "refused": ("Refused", Tone.DESTRUCTIVE),
    "failed": ("Failed", Tone.DESTRUCTIVE),
}
STATUS_REFRESH_SECONDS = 3
STATUS_LIVE_KEYS = ("status", "progress", "requests")


def _split_list(raw: str) -> list[str]:
    return [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _count(value: int, singular: str, plural: str | None = None) -> str:
    return f"{value:,} {singular if value == 1 else (plural or singular + 's')}"


def _result_summary(result: dict[str, Any]) -> str:
    # A successful rerun call answers with the id of the job it queued. Anything
    # else is an error message, which the operator needs to read in full.
    if result["status_code"] == 200:
        try:
            return f"Job {json.loads(result['detail'])['rerun_job_id']}"
        except (ValueError, KeyError, TypeError):
            pass
    if not result["status_code"]:
        return "No response from the CDP API. See the worker logs for the error."
    return result["detail"][:200]


class ReplayFiltersForm(forms.Form):
    window_start = forms.DateTimeField(help_text="UTC, inclusive. For example 2026-10-22 11:30:00.")
    window_end = forms.DateTimeField(
        help_text=f"UTC, exclusive. At most {RERUN_MAX_WINDOW_DAYS} days after the start, because older runs are deleted."
    )
    error_message_contains = forms.CharField(
        required=False,
        label="Error message contains",
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
    team_ids = forms.CharField(
        required=False, label="Team IDs", help_text="Comma-separated. Leave empty for every team."
    )
    template_ids = forms.CharField(
        required=False,
        label="Template IDs",
        help_text=(
            "Comma-separated. Leave empty for every template, custom functions included. "
            "A workflow matches when one of its steps uses the template."
        ),
    )
    exclude_template_ids = forms.CharField(
        required=False,
        label="Exclude template IDs",
        help_text="Comma-separated. Use for destinations where a late send is noise, like template-github.",
    )
    latest_per_person_template_ids = forms.CharField(
        required=False,
        label="Latest run per person for template IDs",
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


class SendReplayForm(forms.Form):
    fingerprint = forms.CharField(widget=forms.HiddenInput)
    confirm_count = forms.CharField(label="Number of runs to send")
    reason = forms.CharField(widget=forms.Textarea, help_text="Goes into the audit log. For example the incident link.")


class AllowResendForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea, help_text="Goes into the audit log. Say how you checked the destinations."
    )


def _tool_url(query: QueryDict | dict[str, str] | None = None) -> str:
    url = reverse("admin_console_tool", kwargs={"tool_key": TOOL_KEY})
    if not query:
        return url
    encoded = query.urlencode() if isinstance(query, QueryDict) else urlencode(query)
    return f"{url}?{encoded}"


def _filters_query(request: HttpRequest, **extra: str) -> QueryDict:
    query = QueryDict(mutable=True)
    for name in ReplayFiltersForm.base_fields:
        if name in request.GET:
            query[name] = request.GET[name]
    for name, value in extra.items():
        query[name] = value
    return query


def _team_cell(team_id: int, team_name: str) -> Cell:
    return Cell(
        text=team_name or f"Team {team_id}",
        href=reverse("admin_console_team", kwargs={"pk": team_id}),
        detail=f"Team {team_id}",
    )


def _targets_label(plan: ReplayPlan) -> str:
    return "Destinations and workflows" if plan.criteria.include_workflows else "Destinations"


def _admin_url(function_kind: str, function_id: str) -> str:
    view = "admin:workflows_hogflow_change" if function_kind == "hog_flow" else "admin:cdp_hogfunction_change"
    return reverse(view, args=[function_id])


def _template_cell(template_id: str) -> Cell:
    if template_id == WORKFLOWS_TEMPLATE_KEY:
        return Cell(text="Workflows")
    return Cell(text=template_id or "Custom function", mono=bool(template_id))


def _window_notice(plan: ReplayPlan) -> Notice:
    criteria = plan.criteria
    parts = [f"{criteria.window_start:%Y-%m-%d %H:%M:%S} to {criteria.window_end:%Y-%m-%d %H:%M:%S} UTC"]
    if criteria.error_message_contains:
        parts.append(f'error contains "{criteria.error_message_contains}"')
    if criteria.error_kinds:
        parts.append(f"error kinds {', '.join(criteria.error_kinds)}")
    return Notice(text=f"Nothing has been sent yet. Window {', '.join(parts)}.")


def _plan_tables(plan: ReplayPlan) -> list[Block]:
    tables: list[Block] = []
    if plan.invocation_count:
        tables.append(
            Table(
                title="Runs by template",
                columns=("Template", "Runs to replay"),
                numeric_columns=(1,),
                rows=tuple(
                    Row(
                        cells=(
                            _template_cell(template_id),
                            Cell(text=f"{count:,}"),
                        )
                    )
                    for template_id, count in plan.invocations_by_template.items()
                    if count
                ),
            )
        )
    if plan.skipped:
        tables.append(
            Table(
                title="Not replayed",
                columns=("Reason", "Runs"),
                numeric_columns=(1,),
                rows=tuple(
                    Row(cells=(Cell(text=SKIP_REASON_LABELS[reason]), Cell(text=f"{count:,}")))
                    for reason, count in plan.skipped.items()
                ),
            )
        )
    return tables


def _teams_table(plan: ReplayPlan) -> Table:
    return Table(
        title="Teams",
        scrolls=True,
        columns=("Team", "Organization", _targets_label(plan), "Runs to replay"),
        numeric_columns=(2, 3),
        rows=tuple(
            Row(
                cells=(
                    _team_cell(team.team_id, team.team_name),
                    Cell(text=team.organization_name),
                    Cell(text=f"{team.function_count:,}"),
                    Cell(text=f"{team.invocation_count:,}"),
                )
            )
            for team in plan.teams
        ),
    )


def _destinations_table(plan: ReplayPlan) -> Table:
    return Table(
        title=_targets_label(plan),
        scrolls=True,
        columns=(
            "Team",
            "Destination or workflow" if plan.criteria.include_workflows else "Destination",
            "Template",
            "Runs to replay",
            "Not replayed",
        ),
        numeric_columns=(3,),
        rows=tuple(
            Row(
                cells=(
                    _team_cell(function.team_id, function.team_name),
                    Cell(
                        text=function.function_name or "No name",
                        href=_admin_url(function.function_kind, function.function_id),
                        detail=function.function_id,
                    ),
                    Cell(text="Workflow")
                    if function.function_kind == "hog_flow"
                    else _template_cell(function.template_id),
                    Cell(text=f"{len(function.invocation_ids):,}", muted=not function.invocation_ids),
                    Cell(
                        text="\n".join(
                            f"{count:,}: {SKIP_REASON_LABELS[reason]}" for reason, count in function.skipped.items()
                        )
                        or "-",
                        muted=True,
                    ),
                )
            )
            for function in plan.functions
        ),
    )


class ReplayStatus:
    """The state of one sent plan, read once per request, so every block on the status page agrees."""

    def __init__(self, fingerprint: str, state: dict[str, Any], can_release: bool) -> None:
        self.fingerprint = fingerprint
        self.state = state
        self.can_release = can_release
        self.results: list[dict[str, Any]] = state.get("results", [])
        self.failed = sum(1 for result in self.results if result["status_code"] != 200)
        self.in_progress = state["status"] in ("queued", "running")

    @classmethod
    def load(cls, fingerprint: str) -> "ReplayStatus | None":
        state = get_replay_state(fingerprint)
        if not state:
            return None
        return cls(fingerprint, state, can_release_replay(fingerprint))

    @property
    def refresh_seconds(self) -> int | None:
        return STATUS_REFRESH_SECONDS if self.in_progress and not self.can_release else None

    def stats(self) -> Stats:
        label, tone = STATUS_LABELS.get(self.state["status"], (self.state["status"], Tone.INFO))
        if self.state["status"] == "done" and self.failed:
            label, tone = "Finished with errors", Tone.DESTRUCTIVE
        return Stats(
            items=(
                Stat(label="Status", value=label, tone=tone),
                Stat(label="Runs in the plan", value=f"{self.state['invocation_count']:,}"),
                Stat(label="Requests sent", value=f"{len(self.results):,} / {self.state['request_count']:,}"),
                Stat(label="Requests failed", value=f"{self.failed:,}"),
            )
        )

    def progress_notice(self) -> Notice:
        if self.refresh_seconds:
            return Notice(
                text=f"The replay is sending in the background. This page refreshes every {STATUS_REFRESH_SECONDS} seconds.",
                tone=Tone.INFO,
            )
        # The notices and actions for a finished send are only on a fresh page.
        return Notice(
            text="The replay is no longer sending.",
            link_text="Show the result",
            href=_tool_url({"plan": self.fingerprint}),
            tone=Tone.INFO,
        )

    def requests_table(self) -> Table:
        return Table(
            title="Requests sent",
            scrolls=True,
            columns=(
                "Team",
                "Destination or workflow"
                if any(result.get("function_kind") == "hog_flow" for result in self.results)
                else "Destination",
                "Runs",
                "HTTP status",
                "Rerun job or error",
            ),
            numeric_columns=(2, 3),
            empty_text="No requests sent yet.",
            rows=tuple(
                Row(
                    cells=(
                        Cell(
                            text=f"Team {result['team_id']}",
                            href=reverse("admin_console_team", kwargs={"pk": result["team_id"]}),
                        ),
                        Cell(
                            text=result["function_id"],
                            href=_admin_url(result.get("function_kind", "hog_function"), result["function_id"]),
                            mono=True,
                        ),
                        Cell(text=f"{result['invocation_count']:,}"),
                        Cell(text=str(result["status_code"] or "No response")),
                        Cell(text=_result_summary(result), muted=result["status_code"] == 200),
                    )
                )
                for result in self.results
            ),
        )

    def live(self, key: str) -> Live:
        blocks: dict[str, Callable[[], Stats | Notice | Table]] = {
            "status": self.stats,
            "progress": self.progress_notice,
            "requests": self.requests_table,
        }
        return Live(key=key, block=blocks[key](), refresh_seconds=self.refresh_seconds)


@console.register_tool
class ReplayFailedRunsTool(ConsoleTool):
    key = TOOL_KEY
    title = "Replay failed CDP runs"
    owner = WORKFLOWS
    group = "Incidents"
    description = "Send failed destination and workflow runs from an incident window again, across teams. You review the runs first."

    def _filters_form(self, request: HttpRequest) -> ReplayFiltersForm | None:
        if "window_start" not in request.GET:
            return None
        return ReplayFiltersForm(request.GET)

    def _send(self, request: HttpRequest, form: forms.Form | None) -> HttpResponse | None:
        assert form is not None
        filters = self._filters_form(request)
        if filters is None or not filters.is_valid():
            messages.error(request, "The filters are not valid, so nothing was sent. Review them again.")
            return HttpResponse(status=400)
        plan = plan_replay(filters.to_criteria())
        # The console's audit line ends in a redirect for a send, a refusal and an "already sent" alike.
        audit = logger.bind(fingerprint=plan.fingerprint, actor=f"admin:{request.user.pk}")
        if form.cleaned_data["fingerprint"] != plan.fingerprint:
            audit.info("cdp_replay_send_refused", reason="plan_changed")
            messages.error(request, "The runs changed since you reviewed them, so nothing was sent. Review them again.")
            return redirect(_tool_url(_filters_query(request, step="details")))
        typed = form.cleaned_data["confirm_count"].replace(",", "").strip()
        if typed != str(plan.invocation_count):
            messages.error(request, f"Type {plan.invocation_count} to confirm. Nothing was sent.")
            return HttpResponse(status=400)
        try:
            sent = dispatch_invocation_replay(plan, actor=f"admin:{request.user.pk}")
        except ReplayOverlapError as error:
            audit.info("cdp_replay_send_refused", reason="overlap")
            messages.error(request, f"{error} Nothing was sent.")
            return HttpResponse(status=409)
        if not sent:
            audit.info("cdp_replay_send_refused", reason="already_sent")
            messages.warning(request, "This plan was already sent, so it was not sent again.")
            return redirect(_tool_url({"plan": plan.fingerprint}))
        audit.info("cdp_replay_send_dispatched", runs=plan.invocation_count)
        return redirect(_tool_url({"plan": plan.fingerprint}))

    def _allow_resend(self, request: HttpRequest, form: forms.Form | None) -> HttpResponse | None:
        fingerprint = request.GET["plan"]
        if release_replay_claim(fingerprint, actor=f"admin:{request.user.pk}"):
            messages.success(request, "This plan can be sent again. Preview the same filters to send it.")
            return None
        messages.error(request, "This plan is still being sent, so it cannot be released yet.")
        return HttpResponse(status=409)

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        if "plan" in request.GET:
            if not can_release_replay(request.GET["plan"]):
                return []
            return [
                ToolOperation(
                    key="allow-resend",
                    label="Allow resending this plan",
                    handler=self._allow_resend,
                    form_class=AllowResendForm,
                    danger=True,
                    description="Only when the destinations show that the runs in this plan were not queued.",
                    undo_hint="This cannot be undone. A resend of runs that were queued sends them twice.",
                    pending_label="Allowing...",
                )
            ]
        # The details page links here with the plan staff reviewed, so the send compares against that plan.
        # Only the operation page offers it: links back to the tool keep the query, and a details page planned
        # again must not show a send for the plan reviewed before.
        if "window_start" not in request.GET or "reviewed" not in request.GET:
            return []
        if request.resolver_match is None or request.resolver_match.url_name != "admin_console_tool_operation":
            return []
        runs, destinations, teams = (request.GET.get(name, "") for name in ("runs", "destinations", "teams"))
        description = ""
        if runs.isdigit() and destinations.isdigit() and teams.isdigit():
            targets = (
                _count(int(destinations), "destination or workflow", "destinations and workflows")
                if request.GET.get("include_workflows")
                else _count(int(destinations), "destination")
            )
            description = (
                f"This queues {_count(int(runs), 'run')} for {targets} "
                f"in {_count(int(teams), 'team')}. Type {runs} to confirm."
            )
        return [
            ToolOperation(
                key="send",
                label="Send replay",
                handler=self._send,
                form_class=SendReplayForm,
                form_initial={"fingerprint": request.GET["reviewed"]},
                danger=True,
                description=description,
                undo_hint="This cannot be undone. The destinations receive these requests again.",
                pending_label="Sending...",
            )
        ]

    def page(self, request: HttpRequest) -> Page:
        if "plan" in request.GET:
            return self._status_page(request.GET["plan"])
        filters = self._filters_form(request)
        if filters is None:
            return self._filters_page(ReplayFiltersForm())
        if request.GET.get("edit") or not filters.is_valid():
            return self._filters_page(filters)
        try:
            plan = plan_replay(filters.to_criteria())
        except Exception as error:
            capture_exception(error)
            return self._filters_page(
                filters,
                error="The runs could not be loaded, so nothing was sent. Try again, or narrow the window.",
            )
        return self._plan_page(request, plan)

    def live(self, request: HttpRequest, key: str) -> Live | None:
        if key not in STATUS_LIVE_KEYS:
            return None
        status = ReplayStatus.load(request.GET.get("plan", ""))
        if status is None:
            return None
        return status.live(key)

    def _filters_page(self, form: ReplayFiltersForm, error: str = "") -> Page:
        blocks: list[Block] = [
            Notice(
                text=(
                    "The next page shows how many destinations, workflows, teams and runs this covers. "
                    "Nothing is sent until you confirm on the details page."
                )
            )
        ]
        if error:
            blocks.append(Notice(text=error, tone=Tone.DESTRUCTIVE))
        blocks.append(Filters(form=form, groups=FILTER_GROUPS, submit_label="Preview", pending_label=PLANNING_LABEL))
        return Page(blocks=tuple(blocks))

    def _plan_page(self, request: HttpRequest, plan: ReplayPlan) -> Page:
        details = request.GET.get("step") == "details" and plan.invocation_count > 0
        change_filters = Link(label="Change the filters", href=_tool_url(_filters_query(request, edit="1")))
        blocks: list[Block] = [
            _window_notice(plan),
            Stats(
                items=(
                    Stat(label=_targets_label(plan), value=f"{len(plan.replayable_functions):,}"),
                    Stat(label="Teams", value=f"{plan.team_count:,}"),
                    Stat(label="Runs to replay", value=f"{plan.invocation_count:,}"),
                )
            ),
        ]
        if plan.invocation_count == 0:
            blocks.append(
                Notice(text="No failed runs to replay. Check the window and the error filter.", tone=Tone.INFO)
            )
        if not details:
            links = [change_filters]
            if plan.invocation_count:
                links.insert(
                    0,
                    Link(
                        label="Show details",
                        href=_tool_url(_filters_query(request, step="details")),
                        primary=True,
                        pending_label=PLANNING_LABEL,
                    ),
                )
            blocks.append(Links(items=tuple(links)))
            blocks.extend(_plan_tables(plan))
            if plan.teams:
                blocks.append(_teams_table(plan))
            return Page(blocks=tuple(blocks))

        blocks.append(
            Links(
                items=(
                    Link(
                        label="Back to the summary",
                        href=_tool_url(_filters_query(request)),
                        pending_label=PLANNING_LABEL,
                    ),
                    change_filters,
                )
            )
        )
        blocks.extend(_plan_tables(plan))
        blocks.append(_destinations_table(plan))
        send_url = reverse("admin_console_tool_operation", kwargs={"tool_key": TOOL_KEY, "operation_key": "send"})
        send_query = _filters_query(
            request,
            step="details",
            reviewed=plan.fingerprint,
            runs=str(plan.invocation_count),
            destinations=str(len(plan.replayable_functions)),
            teams=str(plan.team_count),
        )
        blocks.append(
            Links(items=(Link(label="Send replay", href=f"{send_url}?{send_query.urlencode()}", primary=True),))
        )
        blocks.append(
            Notice(
                text=f"Plan {plan.fingerprint}. If the runs change before you send, nothing is sent and the new plan is shown."
            )
        )
        return Page(blocks=tuple(blocks))

    def _status_page(self, fingerprint: str) -> Page:
        start_new = Links(items=(Link(label="Start a new replay", href=_tool_url()),))
        status = ReplayStatus.load(fingerprint)
        if status is None:
            return Page(
                blocks=(
                    Notice(
                        text=f"No replay is recorded for plan {fingerprint}. It was never sent, or its record expired.",
                        tone=Tone.DESTRUCTIVE,
                    ),
                    start_new,
                )
            )
        state = status.state
        blocks: list[Block] = [status.live("status")]
        if state.get("detail"):
            blocks.append(
                Notice(
                    text=state["detail"],
                    tone=Tone.DESTRUCTIVE if state["status"] != "done" or status.can_release else Tone.INFO,
                )
            )
        if status.in_progress and status.can_release:
            blocks.append(
                Notice(
                    text=(
                        "This replay has not reported progress for 15 minutes, so its worker probably stopped. "
                        "Some runs may still have been queued. Check them on the destinations before you allow a resend."
                    ),
                    tone=Tone.DESTRUCTIVE,
                )
            )
        elif status.in_progress:
            blocks.append(status.live("progress"))
        if state["status"] == "done" and status.failed and not status.can_release:
            blocks.append(
                Notice(
                    text=(
                        "Some requests failed. Preview the same filters again: the runs that went through are no "
                        "longer failed, so the new plan holds only the rest."
                    ),
                    tone=Tone.DESTRUCTIVE,
                )
            )
        if status.results or status.refresh_seconds:
            blocks.append(status.live("requests"))
        blocks.append(Notice(text=f"Plan {fingerprint}, sent by {state['actor']}."))
        blocks.append(start_new)
        return Page(blocks=tuple(blocks))
