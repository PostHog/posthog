"""Schema, prompt builder, and Temporal activities for PostHog Code alert investigations.

Produces:
- ``AlertInvestigationReport`` — the structured output schema the agent must emit.
- ``list_team_investigation_skills`` — returns sorted names of live investigation skills.
- ``build_investigation_prompt`` — constructs the investigation prompt from alert + check context.
- Four Temporal activities: create / poll / finalize / cancel an investigation task run.
"""

from __future__ import annotations

import json
import dataclasses
from datetime import datetime, timedelta
from typing import Any, Literal

import structlog
import temporalio.common
import temporalio.activity
import temporalio.workflow
from pydantic import BaseModel, Field

from posthog.models.organization import OrganizationMembership
from posthog.sync import database_sync_to_async
from posthog.tasks.alerts.utils import build_alert_firing_context
from posthog.temporal.alerts.investigation import get_episode_start
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.utils import absolute_uri

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, InvestigationStatus
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

INVESTIGATION_SKILL_PREFIX = "investigation-"
INVESTIGATION_SKILL_CATEGORY = "investigation"


class AlertInvestigationReport(BaseModel):
    """Structured output the investigation agent writes at the end of a run.

    Verdict semantics:
    - ``true_positive``: the breach warrants action — something real broke or regressed.
    - ``false_positive``: the breach is real but expected or benign (seasonality, known
      deploy, test traffic, data pipeline quirk).
    - ``inconclusive``: insufficient evidence to classify confidently.
    """

    findings: str = Field(description="Factual summary of what the agent observed.")
    suspected_cause: str = Field(description="Most likely root cause of the firing.")
    proposed_mitigation: str = Field(description="Concrete next step or fix to address the cause.")
    confidence: float = Field(
        ge=0,
        le=1,
        description="Agent's confidence in the verdict, from 0 (no idea) to 1 (certain).",
    )
    verdict: Literal["true_positive", "false_positive", "inconclusive"] = Field(
        description=(
            "Classification of the alert firing. "
            "'true_positive' = warrants action. "
            "'false_positive' = breach is real but expected or benign "
            "(seasonality, known deploy, test traffic). "
            "'inconclusive' = insufficient evidence to classify."
        )
    )
    pr_url: str | None = Field(
        default=None,
        description="URL of the draft PR opened by the agent, if any.",
    )


def list_team_investigation_skills(team_id: int) -> list[str]:
    """Return sorted names of live ``investigation-*`` LLMSkills for the given team.

    Side-effect: rows whose ``category`` is empty are stamped with
    ``INVESTIGATION_SKILL_CATEGORY`` so future queries can filter by category directly.
    """
    qs = LLMSkill.objects.filter(
        team_id=team_id,
        deleted=False,
        is_latest=True,
        name__startswith=INVESTIGATION_SKILL_PREFIX,
    )
    # Stamp category on rows that haven't been classified yet.
    qs.filter(category="").update(category=INVESTIGATION_SKILL_CATEGORY)
    return sorted(qs.values_list("name", flat=True))


def build_investigation_prompt(
    alert: AlertConfiguration,
    alert_check: AlertCheck,
    *,
    firing_context: dict[str, Any],
    skill_names: list[str],
    previous_task_run_id: str | None,
) -> str:
    """Build the investigation prompt sent to the PostHog Code agent.

    Sections (in order):
    1. Header with alert name and mode detail.
    2. Breach values from ``firing_context``.
    3. Insight and dashboard deep links.
    4. Insight-vs-dashboard-filters caveat.
    5. Baseline skill instruction and team skill listing.
    6. Previous-run section (only on reruns).
    7. Alert owner's instructions (only when ``investigation_context`` is set).
    8. Structured-output closing instruction.
    """
    team_id = alert.team_id
    insight = alert.insight

    # --- Section 1: Header ---
    detector_config = alert.detector_config or {}
    detector_type = detector_config.get("type")
    if detector_type:
        mode_detail = f"**Mode:** Detector-based anomaly detection (type: `{detector_type}`)"
    else:
        threshold_lower = firing_context.get("threshold_lower")
        threshold_upper = firing_context.get("threshold_upper")
        bounds_str = f"lower={threshold_lower}, upper={threshold_upper}"
        mode_detail = f"**Mode:** Threshold-based alert (bounds: {bounds_str})"

    header = f"# Investigate alert firing: {alert.name}\n\n{mode_detail}"

    # --- Section 2: Breach values ---
    alert_check_id = firing_context["alert_check_id"]
    calculated_value = firing_context["calculated_value"]
    threshold_lower = firing_context.get("threshold_lower")
    threshold_upper = firing_context.get("threshold_upper")
    dashboard_ids: list[int] = firing_context.get("dashboard_ids") or []

    breach_lines = [
        "## Breach values",
        f"- **Alert check ID:** `{alert_check_id}`",
        f"- **Calculated value:** {calculated_value}",
    ]
    if threshold_lower is not None:
        breach_lines.append(f"- **Threshold lower:** {threshold_lower}")
    if threshold_upper is not None:
        breach_lines.append(f"- **Threshold upper:** {threshold_upper}")
    breach_section = "\n".join(breach_lines)

    # --- Section 3: Insight and dashboard deep links ---
    insight_url = absolute_uri(f"/project/{team_id}/insights/{insight.short_id}")
    links_lines = [
        "## Data links",
        f"- **Insight** (`{insight.short_id}`): {insight_url}",
    ]
    for d_id in dashboard_ids:
        dashboard_url = absolute_uri(f"/project/{team_id}/dashboard/{d_id}")
        links_lines.append(f"- **Dashboard {d_id}:** {dashboard_url}")
    links_section = "\n".join(links_lines)

    # --- Section 4: Insight-vs-dashboard-filters caveat ---
    caveat_section = (
        "## Important: insight vs dashboard filters\n\n"
        "The breach values above come from the insight's **own configuration** — the query "
        "as stored on the insight itself. An insight can be embedded on several dashboards "
        "(or none), each of which may apply its own date-range or filter overrides. "
        "Numbers visible on a dashboard may therefore legitimately differ from the alerted "
        "value. Treat dashboard views as supporting context, not the canonical breach source."
    )

    # --- Section 5: Skills ---
    skills_lines = [
        "## Investigation skills",
        "Start by invoking the `investigating-alert-firings` skill for the baseline investigation playbook.",
    ]
    if skill_names:
        names_list = ", ".join(f"`{n}`" for n in skill_names)
        skills_lines.append(
            f"This team maintains additional investigation skills in PostHog — read them "
            f"with the skill MCP tools before diving in: {names_list}. "
            "If the alert owner names a specific skill below, prefer it."
        )
    skills_section = "\n\n".join(skills_lines)

    # --- Section 6: Previous-run context (reruns only) ---
    previous_run_section = ""
    if previous_task_run_id:
        previous_run_section = (
            "## Rerun context\n\n"
            f"This is a re-run: the alert is still firing. "
            f"Build on the previous investigation (task run `{previous_task_run_id}`) — "
            "update its draft PR and findings rather than starting cold or opening a duplicate PR."
        )

    # --- Section 7: Alert owner's instructions ---
    owner_instructions_section = ""
    if alert.investigation_context:
        owner_instructions_section = f"## Alert owner's instructions\n\n{alert.investigation_context}"

    # --- Section 8: Structured-output closing instruction ---
    closing_section = (
        "## Structured output\n\n"
        "Finish by setting your structured output to an `AlertInvestigationReport` with: "
        "`findings`, `suspected_cause`, `proposed_mitigation`, `confidence` (0–1), "
        "`verdict` (`true_positive` | `false_positive` | `inconclusive`), and optionally `pr_url`."
    )

    sections = [
        header,
        breach_section,
        links_section,
        caveat_section,
        skills_section,
    ]
    if previous_run_section:
        sections.append(previous_run_section)
    if owner_instructions_section:
        sections.append(owner_instructions_section)
    sections.append(closing_section)

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Activity input / output dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PostHogCodeInvestigationInputs:
    team_id: int
    alert_id: str
    alert_check_id: str


@dataclasses.dataclass(frozen=True)
class CreateInvestigationTaskResult:
    status: str  # "created" | "skipped" | "failed"
    task_run_id: str | None = None
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class InvestigationRunState:
    terminal: bool
    status: str | None = None  # TaskRun.Status value
    output: dict | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}


def _get_previous_task_run_id(alert: AlertConfiguration, alert_check: AlertCheck) -> str | None:
    """Return the latest earlier AlertCheck's investigation_task_run_id in the current firing episode."""
    episode_start: datetime | None = get_episode_start(alert)
    qs = AlertCheck.objects.filter(
        alert_configuration=alert,
        investigation_task_run_id__isnull=False,
    ).exclude(id=alert_check.id)
    if episode_start is not None:
        qs = qs.filter(created_at__gt=episode_start)
    row = qs.order_by("-created_at").values_list("investigation_task_run_id", flat=True).first()
    return str(row) if row is not None else None


def _is_active_org_member(user_id: int, organization_id: int) -> bool:
    """True when the user is active and has an OrganizationMembership in the given org."""
    from posthog.models import User  # noqa: PLC0415 — avoid circular import at module level

    if not User.objects.filter(id=user_id, is_active=True).exists():
        return False
    return OrganizationMembership.objects.filter(user_id=user_id, organization_id=organization_id).exists()


# ---------------------------------------------------------------------------
# Temporal activities
# ---------------------------------------------------------------------------


@temporalio.activity.defn
async def create_posthog_code_investigation_task(
    inputs: PostHogCodeInvestigationInputs,
) -> CreateInvestigationTaskResult:
    """Create a PostHog Code task to investigate an alert firing.

    Idempotent: if ``investigation_task_run_id`` is already set on the check (Temporal retry),
    returns the existing result without calling the facade again.

    Never raises — investigation failures are written to the check and returned as
    ``status="failed"`` so they don't poison the surrounding alert workflow.
    """

    @database_sync_to_async(thread_sensitive=False)
    def _create() -> CreateInvestigationTaskResult:
        try:
            alert = AlertConfiguration.objects.select_related(
                "insight", "team", "team__organization", "threshold", "created_by"
            ).get(id=inputs.alert_id)
        except AlertConfiguration.DoesNotExist:
            logger.warning(
                "create_investigation: alert not found",
                alert_id=inputs.alert_id,
            )
            return CreateInvestigationTaskResult(status="failed", reason="alert_not_found")

        try:
            alert_check = AlertCheck.objects.get(id=inputs.alert_check_id, alert_configuration_id=inputs.alert_id)
        except AlertCheck.DoesNotExist:
            logger.warning(
                "create_investigation: alert_check not found",
                alert_check_id=inputs.alert_check_id,
            )
            return CreateInvestigationTaskResult(status="failed", reason="alert_check_not_found")

        team = alert.team

        # Idempotency: already created (Temporal activity retry).
        if alert_check.investigation_task_run_id is not None:
            return CreateInvestigationTaskResult(
                status="created",
                task_run_id=str(alert_check.investigation_task_run_id),
            )

        # Identity check: alert must have an active org member as owner.
        created_by_id = alert.created_by_id
        if created_by_id is None or not _is_active_org_member(created_by_id, team.organization_id):
            AlertCheck.objects.filter(id=alert_check.id).update(
                investigation_status=InvestigationStatus.SKIPPED,
                investigation_error={"reason": "investigation needs an owner"},
            )
            return CreateInvestigationTaskResult(status="skipped", reason="no_active_owner")

        try:
            previous_task_run_id = _get_previous_task_run_id(alert, alert_check)
            firing_context = build_alert_firing_context(alert, alert_check)
            skill_names = list_team_investigation_skills(inputs.team_id)
            prompt = build_investigation_prompt(
                alert,
                alert_check,
                firing_context=firing_context,
                skill_names=skill_names,
                previous_task_run_id=previous_task_run_id,
            )

            created = tasks_facade.create_and_run_task(
                team=team,
                title=f"Investigate alert firing: {alert.name}"[:255],
                description=prompt,
                origin_product=tasks_facade.TaskOriginProduct.ALERT,
                user_id=alert.created_by_id,
                repository=alert.investigation_repository,
                create_pr=bool(alert.investigation_repository),
                posthog_mcp_scopes="read_only",
                output_schema=AlertInvestigationReport,
            )

            if created.latest_run is None:
                raise RuntimeError("create_and_run_task returned no latest_run")

            run_id = created.latest_run.id
            AlertCheck.objects.filter(id=alert_check.id).update(
                investigation_task_run_id=run_id,
                investigation_status=InvestigationStatus.RUNNING,
            )
            dashboard_ids: list[int] = firing_context.get("dashboard_ids") or []
            tasks_facade.update_task_run_state(
                run_id,
                updates={
                    "alert_id": str(alert.id),
                    "alert_check_id": str(alert_check.id),
                    "insight_short_id": alert.insight.short_id,
                    "dashboard_ids": dashboard_ids,
                },
            )
            return CreateInvestigationTaskResult(status="created", task_run_id=str(run_id))

        except Exception as exc:
            reason = str(exc)[:500]
            logger.exception(
                "create_investigation: failed to create task",
                alert_id=inputs.alert_id,
                alert_check_id=inputs.alert_check_id,
                exc_info=exc,
            )
            AlertCheck.objects.filter(id=alert_check.id).update(
                investigation_status=InvestigationStatus.FAILED,
                investigation_error={"reason": reason},
            )
            return CreateInvestigationTaskResult(status="failed", reason=reason)

    async with Heartbeater():
        return await _create()


@temporalio.activity.defn
async def get_investigation_run_state(
    inputs: PostHogCodeInvestigationInputs,
) -> InvestigationRunState:
    """Poll the task run status for an in-progress investigation."""

    @database_sync_to_async(thread_sensitive=False)
    def _poll() -> InvestigationRunState:
        try:
            alert_check = AlertCheck.objects.get(id=inputs.alert_check_id, alert_configuration_id=inputs.alert_id)
        except AlertCheck.DoesNotExist:
            return InvestigationRunState(terminal=True, status="failed")

        run_id = alert_check.investigation_task_run_id
        if run_id is None:
            return InvestigationRunState(terminal=True, status="failed")

        run = tasks_facade.get_task_run(str(run_id), team_id=inputs.team_id)
        if run is None:
            return InvestigationRunState(terminal=True, status="failed")

        terminal = run.status in _TERMINAL_RUN_STATUSES
        return InvestigationRunState(
            terminal=terminal,
            status=run.status,
            output=run.output if terminal else None,
        )

    async with Heartbeater():
        return await _poll()


@temporalio.activity.defn
async def finalize_posthog_code_investigation(
    inputs: PostHogCodeInvestigationInputs,
) -> None:
    """Write the investigation verdict / summary to the AlertCheck once the run completes."""

    @database_sync_to_async(thread_sensitive=False)
    def _finalize() -> None:
        try:
            alert_check = AlertCheck.objects.get(id=inputs.alert_check_id, alert_configuration_id=inputs.alert_id)
        except AlertCheck.DoesNotExist:
            logger.warning(
                "finalize_investigation: alert_check not found",
                alert_check_id=inputs.alert_check_id,
            )
            return

        run_id = alert_check.investigation_task_run_id
        if run_id is None:
            AlertCheck.objects.filter(id=alert_check.id).update(
                investigation_status=InvestigationStatus.FAILED,
                investigation_error={"reason": "no task run id on check at finalize"},
            )
            return

        run = tasks_facade.get_task_run(str(run_id), team_id=inputs.team_id)
        if run is None:
            AlertCheck.objects.filter(id=alert_check.id).update(
                investigation_status=InvestigationStatus.FAILED,
                investigation_error={"reason": "task run not found at finalize"},
            )
            return

        if run.status == "completed" and run.output is not None:
            try:
                report = AlertInvestigationReport.model_validate(run.output)
            except Exception as exc:
                AlertCheck.objects.filter(id=alert_check.id).update(
                    investigation_status=InvestigationStatus.FAILED,
                    investigation_error={"reason": f"invalid output schema: {exc}"},
                )
                return

            summary = (report.suspected_cause or report.findings)[:500]
            AlertCheck.objects.filter(id=alert_check.id).update(
                investigation_status=InvestigationStatus.DONE,
                investigation_verdict=report.verdict,
                investigation_summary=summary,
                investigation_error=None,
            )
        else:
            reason = f"run ended with status={run.status!r}"
            AlertCheck.objects.filter(id=alert_check.id).update(
                investigation_status=InvestigationStatus.FAILED,
                investigation_error={"reason": reason},
            )

    async with Heartbeater():
        await _finalize()


@temporalio.activity.defn
async def cancel_posthog_code_investigation(
    inputs: PostHogCodeInvestigationInputs,
) -> None:
    """Cancel an in-progress investigation task run and mark the check as FAILED."""

    @database_sync_to_async(thread_sensitive=False)
    def _cancel() -> None:
        try:
            alert_check = AlertCheck.objects.get(id=inputs.alert_check_id, alert_configuration_id=inputs.alert_id)
        except AlertCheck.DoesNotExist:
            logger.warning(
                "cancel_investigation: alert_check not found",
                alert_check_id=inputs.alert_check_id,
            )
            return

        run_id = alert_check.investigation_task_run_id
        if run_id is not None:
            try:
                tasks_facade.send_cancel(str(run_id))
            except Exception:
                logger.exception(
                    "cancel_investigation: send_cancel failed",
                    run_id=str(run_id),
                )

        AlertCheck.objects.filter(id=alert_check.id).update(
            investigation_status=InvestigationStatus.FAILED,
            investigation_error={"reason": "investigation timed out after 60 minutes"},
        )

    async with Heartbeater():
        await _cancel()


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

POSTHOG_CODE_INVESTIGATION_POLL_INTERVAL = timedelta(seconds=30)
POSTHOG_CODE_INVESTIGATION_TIMEOUT = timedelta(minutes=60)


@temporalio.workflow.defn(name="posthog-code-investigation")
class PostHogCodeInvestigationWorkflow(PostHogWorkflow):
    """Drive a PostHog Code investigation task: create, poll to terminal, finalize.

    Started as an abandoned child of CheckAlertWorkflow. If the run doesn't reach a
    terminal state within POSTHOG_CODE_INVESTIGATION_TIMEOUT, cancel it.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> PostHogCodeInvestigationInputs:
        loaded = json.loads(inputs[0])
        return PostHogCodeInvestigationInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: PostHogCodeInvestigationInputs) -> None:
        created = await temporalio.workflow.execute_activity(
            create_posthog_code_investigation_task,
            inputs,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )
        if created.status != "created":
            return

        deadline = temporalio.workflow.now() + POSTHOG_CODE_INVESTIGATION_TIMEOUT
        while temporalio.workflow.now() < deadline:
            state = await temporalio.workflow.execute_activity(
                get_investigation_run_state,
                inputs,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
            )
            if state.terminal:
                await temporalio.workflow.execute_activity(
                    finalize_posthog_code_investigation,
                    inputs,
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
                )
                return
            await temporalio.workflow.sleep(POSTHOG_CODE_INVESTIGATION_POLL_INTERVAL)

        await temporalio.workflow.execute_activity(
            cancel_posthog_code_investigation,
            inputs,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )
