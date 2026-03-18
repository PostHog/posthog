import asyncio
import dataclasses
from uuid import uuid4

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

import structlog

from posthog.temporal.common.client import sync_connect
from posthog.temporal.health_checks.models import HealthCheckWorkflowInputs
from posthog.temporal.health_checks.registry import HEALTH_CHECKS, ensure_registry_loaded

logger = structlog.get_logger(__name__)


class HealthCheckTriggerForm(forms.Form):
    dry_run = forms.BooleanField(required=False, help_text="Run without writing changes to the database")
    batch_size = forms.IntegerField(min_value=1, max_value=10000, help_text="Number of teams per batch")
    max_concurrent = forms.IntegerField(min_value=1, max_value=20, help_text="Max concurrent batch activities")
    rollout_percentage = forms.FloatField(
        min_value=0.01, max_value=1.0, help_text="Fraction of teams to process (0.01 to 1.0)"
    )
    active_since_days = forms.IntegerField(
        required=False,
        min_value=0,
        help_text="Only process teams with org members who logged in within the last N days. 0 or blank = all teams.",
    )
    team_ids = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "e.g. 1, 2, 3"}),
        help_text="Comma-separated team IDs to target (leave blank for all teams)",
    )

    def clean_active_since_days(self) -> int | None:
        value = self.cleaned_data.get("active_since_days")
        if value is None or value == 0:
            return None
        return value

    def clean_team_ids(self) -> list[int] | None:
        raw = self.cleaned_data.get("team_ids", "").strip()
        if not raw:
            return None
        try:
            return [int(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError:
            raise forms.ValidationError("Team IDs must be comma-separated integers")


def health_check_list_view(request):
    # TODO: Add more granular permissions beyond is_staff (e.g. restrict to specific engineering groups)
    if not request.user.is_staff:
        raise PermissionDenied

    ensure_registry_loaded()

    checks = sorted(HEALTH_CHECKS.values(), key=lambda c: c.name)

    context = {
        "checks": checks,
        "title": "Health checks",
        "has_view_permission": True,
        "site_title": admin.site.site_title,
        "site_header": admin.site.site_header,
        "site_url": admin.site.site_url,
        "has_permission": True,
    }
    return render(request, "admin/health_checks/list.html", context)


def health_check_trigger_view(request, kind: str):
    if not request.user.is_staff:
        raise PermissionDenied

    ensure_registry_loaded()

    config = HEALTH_CHECKS.get(kind)
    if config is None:
        messages.error(request, f"Health check '{kind}' not found in registry")
        return redirect("health-checks")

    if request.method == "POST":
        form = HealthCheckTriggerForm(request.POST)
        if form.is_valid():
            workflow_inputs = HealthCheckWorkflowInputs.from_config(config)
            workflow_inputs = dataclasses.replace(
                workflow_inputs,
                dry_run=form.cleaned_data["dry_run"],
                batch_size=form.cleaned_data["batch_size"],
                max_concurrent=form.cleaned_data["max_concurrent"],
                rollout_percentage=form.cleaned_data["rollout_percentage"],
                active_since_days=form.cleaned_data["active_since_days"],
                team_ids=form.cleaned_data["team_ids"],
            )

            try:
                temporal = sync_connect()
                workflow_id = f"health-check-{config.name}-manual-{uuid4()}"
                asyncio.run(
                    temporal.start_workflow(
                        "health-check-workflow",
                        dataclasses.asdict(workflow_inputs),
                        id=workflow_id,
                        task_queue=settings.HEALTH_CHECK_TASK_QUEUE,
                    )
                )
                logger.info(
                    "Health check workflow triggered manually",
                    kind=kind,
                    workflow_id=workflow_id,
                    triggered_by=request.user.email,
                    dry_run=form.cleaned_data["dry_run"],
                )
                messages.success(request, f"Workflow triggered: {workflow_id}")
            except Exception as e:
                logger.exception("Failed to trigger health check workflow", kind=kind, error=str(e))
                messages.error(request, f"Failed to trigger workflow: {e}")

            return redirect("health-check-trigger", kind=kind)
    else:
        form = HealthCheckTriggerForm(
            initial={
                "dry_run": config.dry_run,
                "batch_size": config.batch_size,
                "max_concurrent": config.max_concurrent,
                "rollout_percentage": config.rollout_percentage,
                "active_since_days": config.active_since_days,
            }
        )

    workflows = _get_recent_runs(config.name)

    context = {
        **admin.site.each_context(request),
        "config": config,
        "form": form,
        "workflows": workflows,
        "title": f"Health check: {config.name}",
        "temporal_ui_host": settings.TEMPORAL_UI_HOST,
        "temporal_namespace": settings.TEMPORAL_NAMESPACE,
    }
    return render(request, "admin/health_checks/trigger.html", context)


def health_check_runs_fragment_view(request, kind: str):
    if not request.user.is_staff:
        raise PermissionDenied

    ensure_registry_loaded()

    config = HEALTH_CHECKS.get(kind)
    if config is None:
        return render(request, "admin/health_checks/_run_history.html", {"workflows": []})

    workflows = _get_recent_runs(config.name)
    context = {
        "workflows": workflows,
        "temporal_ui_host": settings.TEMPORAL_UI_HOST,
        "temporal_namespace": settings.TEMPORAL_NAMESPACE,
    }
    return render(request, "admin/health_checks/_run_history.html", context)


def _get_recent_runs(config_name: str, limit: int = 20) -> list[dict]:
    try:
        temporal = sync_connect()
        prefix = f"health-check-{config_name}"
        query = f'WorkflowId >= "{prefix}" AND WorkflowId < "{prefix}~" ORDER BY StartTime DESC'

        async def fetch_workflows():
            workflows = []
            async for wf in temporal.list_workflows(query=query):
                workflows.append(
                    {
                        "id": wf.id,
                        "run_id": wf.run_id,
                        "status": str(wf.status.name) if wf.status else "Unknown",
                        "start_time": wf.start_time,
                        "close_time": wf.close_time,
                        "source": "Manual" if "-manual-" in wf.id else "Scheduled",
                    }
                )
                if len(workflows) >= limit:
                    break
            return workflows

        return asyncio.run(fetch_workflows())
    except Exception as e:
        logger.warning("Failed to fetch health check workflows", config_name=config_name, error=str(e))
        return []
