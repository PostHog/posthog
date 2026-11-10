import asyncio
import dataclasses
from datetime import datetime, timedelta
from urllib.parse import urlencode

from django import forms
from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

import structlog
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.admin.console.panels import Tone
from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.admin.console.tools import Cell, ConsoleTool, Live, Notice, Page, Row, Table, ToolOperation
from posthog.dataclasses import frozen
from posthog.temporal.common.client import sync_connect
from posthog.temporal.health_checks.framework import HealthCheckRegistration
from posthog.temporal.health_checks.models import HealthCheckWorkflowInputs
from posthog.temporal.health_checks.registry import HEALTH_CHECKS, ensure_registry_loaded

logger = structlog.get_logger(__name__)

TOOL_URL = "/admin/console/tools/health-checks/"
RECENT_RUNS = 20
REFRESH_SECONDS_WHILE_RUNNING = 10
# Temporal can be away for a moment, so the history keeps asking, just less often.
REFRESH_SECONDS_WHILE_TEMPORAL_IS_AWAY = 30
# Bounds the history read, so a stalled Temporal cannot hold a web worker.
TEMPORAL_READ_TIMEOUT = timedelta(seconds=5)
STATUS_TONES = {
    "RUNNING": Tone.INFO,
    "CONTINUED_AS_NEW": Tone.INFO,
    "COMPLETED": Tone.SUCCESS,
    "FAILED": Tone.DESTRUCTIVE,
    "TERMINATED": Tone.DESTRUCTIVE,
    "TIMED_OUT": Tone.DESTRUCTIVE,
    "CANCELED": Tone.WARNING,
}


class HealthCheckRunForm(forms.Form):
    dry_run = forms.BooleanField(required=False, help_text="Run without writing issues to the database.")
    batch_size = forms.IntegerField(min_value=1, max_value=10000, help_text="Teams per batch.")
    max_concurrent = forms.IntegerField(min_value=1, max_value=20, help_text="Batches that run at the same time.")
    rollout_percentage = forms.FloatField(
        min_value=0.01, max_value=1.0, help_text="Fraction of teams to check, from 0.01 to 1.0."
    )
    active_since_days = forms.IntegerField(
        required=False,
        min_value=0,
        help_text="Only teams with a member who logged in within this many days. 0 or empty checks every team.",
    )
    team_ids = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "1, 2, 3"}),
        help_text="Comma-separated team IDs to check. Leave empty for every team.",
    )

    def clean_active_since_days(self) -> int | None:
        return self.cleaned_data.get("active_since_days") or None

    def clean_team_ids(self) -> list[int] | None:
        raw = self.cleaned_data.get("team_ids", "").strip()
        if not raw:
            return None
        try:
            return [int(part.strip()) for part in raw.split(",") if part.strip()]
        except ValueError:
            raise forms.ValidationError("Enter team IDs as comma-separated numbers.")


@frozen
class HealthCheckRun:
    workflow_id: str
    run_id: str
    status: str
    started: datetime | None
    closed: datetime | None


class HealthCheckRuns:
    """Reads and starts health check workflows in Temporal. Workflow IDs start with the check's name."""

    @staticmethod
    def recent(check: HealthCheckRegistration) -> list[HealthCheckRun] | None:
        """The latest runs, newest first, or None when Temporal cannot be reached."""
        prefix = f"health-check-{check.name}"
        query = f'WorkflowId >= "{prefix}" AND WorkflowId < "{prefix}~" ORDER BY StartTime DESC'

        async def fetch(client: Client) -> list[HealthCheckRun]:
            runs: list[HealthCheckRun] = []
            async for workflow in client.list_workflows(
                query=query, limit=RECENT_RUNS, rpc_timeout=TEMPORAL_READ_TIMEOUT
            ):
                runs.append(
                    HealthCheckRun(
                        workflow_id=workflow.id,
                        run_id=workflow.run_id,
                        status=workflow.status.name if workflow.status else "UNKNOWN",
                        started=workflow.start_time,
                        closed=workflow.close_time,
                    )
                )
                if len(runs) >= RECENT_RUNS:
                    break
            return runs

        try:
            # Connect before the event loop starts: sync_connect refuses to run inside one.
            return asyncio.run(fetch(sync_connect()))
        except Exception:
            logger.warning("admin_console_health_check_runs_unavailable", check=check.name, exc_info=True)
            return None

    @staticmethod
    def start(check: HealthCheckRegistration, form: forms.Form, form_nonce: str) -> str:
        inputs = dataclasses.replace(
            HealthCheckWorkflowInputs.from_config(check),
            dry_run=form.cleaned_data["dry_run"],
            batch_size=form.cleaned_data["batch_size"],
            max_concurrent=form.cleaned_data["max_concurrent"],
            rollout_percentage=form.cleaned_data["rollout_percentage"],
            active_since_days=form.cleaned_data["active_since_days"],
            team_ids=form.cleaned_data["team_ids"],
        )
        # The form nonce names the workflow, so a double submit of one form starts one run.
        workflow_id = f"health-check-{check.name}-manual-{form_nonce}"
        asyncio.run(
            sync_connect().start_workflow(
                "health-check-workflow",
                dataclasses.asdict(inputs),
                id=workflow_id,
                task_queue=settings.HEALTH_CHECK_TASK_QUEUE,
                execution_timeout=check.execution_timeout,
                # Temporal reuses a closed workflow's ID by default, so a resubmit after the run ended would start again.
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        )
        return workflow_id


class RunHealthCheck:
    def __init__(self, check: HealthCheckRegistration) -> None:
        self.check = check

    def __call__(self, request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
        assert form is not None
        form_nonce = request.POST.get("form_nonce", "")
        try:
            workflow_id = HealthCheckRuns.start(self.check, form, form_nonce)
        except WorkflowAlreadyStartedError:
            messages.info(request, "This form already started a run. It shows in the list below.")
            return None
        except Exception as error:
            logger.exception("admin_console_health_check_start_failed", check=self.check.name)
            messages.error(request, f"Could not start the run: {error}")
            return HttpResponse(status=502)
        messages.success(request, f"Started {workflow_id}.")
        # Temporal lists a new run only after a moment, so the page names it and keeps refreshing until it shows.
        return HttpResponseRedirect(f"{TOOL_URL}?{urlencode({'check': self.check.kind, 'started': workflow_id})}")


def _run_row(run: HealthCheckRun) -> Row:
    temporal_url = (
        f"{settings.TEMPORAL_UI_HOST}/namespaces/{settings.TEMPORAL_NAMESPACE}/workflows/{run.workflow_id}/{run.run_id}"
    )
    return Row(
        cells=(
            Cell(text=run.workflow_id, href=temporal_url, mono=True),
            Cell(text="Manual" if "-manual-" in run.workflow_id else "Scheduled"),
            Cell(text=run.status.replace("_", " ").capitalize(), tone=STATUS_TONES.get(run.status)),
            Cell(text=run.started.strftime("%Y-%m-%d %H:%M:%S") if run.started else "-", muted=run.started is None),
            Cell(text=run.closed.strftime("%Y-%m-%d %H:%M:%S") if run.closed else "-", muted=run.closed is None),
        )
    )


def _check_row(check: HealthCheckRegistration) -> Row:
    return Row(
        cells=(
            Cell(text=check.name, href=f"{TOOL_URL}?{urlencode({'check': check.kind})}"),
            Cell(text=check.owner.value),
            Cell(text=check.schedule or "Manual only", mono=bool(check.schedule), muted=not check.schedule),
            Cell(text=f"{check.rollout_percentage:.2f}"),
            Cell(text=f"{check.active_since_days} days" if check.active_since_days else "All teams"),
            Cell(text="Yes" if check.dry_run else "No"),
        )
    )


@console.register_tool
class HealthChecksTool(ConsoleTool):
    key = "health-checks"
    title = "Health checks"
    owner = DEV_EXPERIENCE
    group = "Data"
    description = "Runs a health check across teams and follows its runs in Temporal."

    def _check(self, request: HttpRequest) -> HealthCheckRegistration | None:
        ensure_registry_loaded()
        return HEALTH_CHECKS.get(request.GET.get("check", ""))

    def page(self, request: HttpRequest) -> Page:
        check = self._check(request)
        if check is None:
            ensure_registry_loaded()
            checks = sorted(HEALTH_CHECKS.values(), key=lambda registered: registered.name)
            return Page(
                blocks=(
                    Notice(text="Pick a check to run it and see its recent runs."),
                    Table(
                        columns=("Check", "Owner", "Schedule", "Rollout", "Active since", "Dry run"),
                        rows=tuple(_check_row(registered) for registered in checks),
                        empty_text="No health checks are registered. Product modules register them in the registry.",
                    ),
                )
            )
        runs = self.live(request, "runs")
        assert runs is not None
        return Page(
            blocks=(
                Notice(
                    text=f"{check.name}, owned by {check.owner.value}.", link_text="All health checks", href=TOOL_URL
                ),
                runs,
            )
        )

    def live(self, request: HttpRequest, key: str) -> Live | None:
        check = self._check(request)
        if key != "runs" or check is None:
            return None
        runs = HealthCheckRuns.recent(check)
        if runs is None:
            return Live(
                key="runs",
                block=Notice(text="Temporal did not answer, so the runs cannot be shown. This retries on its own."),
                refresh_seconds=REFRESH_SECONDS_WHILE_TEMPORAL_IS_AWAY,
            )
        # A run that continued as new is closed; its successor shows as its own running row.
        running = any(run.status == "RUNNING" for run in runs)
        started = request.GET.get("started")
        waiting_for_new_run = started is not None and all(run.workflow_id != started for run in runs)
        return Live(
            key="runs",
            block=Table(
                columns=("Workflow", "Source", "Status", "Started", "Finished"),
                rows=tuple(_run_row(run) for run in runs),
                empty_text="This check has not run yet.",
            ),
            refresh_seconds=REFRESH_SECONDS_WHILE_RUNNING if running or waiting_for_new_run else None,
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        check = self._check(request)
        if check is None:
            return []
        return [
            ToolOperation(
                key="run",
                label=f"Run {check.name}",
                handler=RunHealthCheck(check),
                description="Starts a run now, with the settings you pick.",
                form_class=HealthCheckRunForm,
                form_initial={
                    "dry_run": check.dry_run,
                    "batch_size": check.batch_size,
                    "max_concurrent": check.max_concurrent,
                    "rollout_percentage": check.rollout_percentage,
                    "active_since_days": check.active_since_days,
                },
            )
        ]


console.register_moved_page(old_path="admin/health-checks/", title="Health checks", url=TOOL_URL)
console.register_moved_page(
    old_path="admin/health-checks/<str:kind>/",
    title="Health checks",
    url=f"{TOOL_URL}?check={{kind}}",
)
console.register_moved_page(
    old_path="admin/health-checks/<str:kind>/runs/",
    title="Health checks",
    url=f"{TOOL_URL}?check={{kind}}",
)
