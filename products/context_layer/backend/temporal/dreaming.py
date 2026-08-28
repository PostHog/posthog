"""Nightly dreaming: one sandboxed run per enabled organization that
synthesizes the org's activity onto a dated `dream/<date>` branch.

The coordinator only dispatches: each dream runs as a normal cloud task in the
tasks product, works unlocked on its own clone, and lands its branch through
the commits endpoint (one merge commit per night). Modeled on the signals scout
coordinator: skip-overlap per day, a per-org failure-streak circuit breaker,
and a hard cap on dispatches per tick.
"""

from __future__ import annotations

import uuid
import asyncio
import datetime as dt
import functools
from pathlib import Path

from django.conf import settings
from django.db.models import F
from django.utils import timezone

import structlog
import temporalio.common
import temporalio.workflow
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.common import WorkflowIDReusePolicy

from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.ph_client import ph_scoped_capture
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import sync_connect

from products.context_layer.backend.facade import api as context_layer_facade
from products.context_layer.backend.models import ContextLayerConfig

logger = structlog.get_logger(__name__)

DISPATCH_CAP_PER_TICK = 1000
# Dispatch failures, not run failures: a lane pauses when we cannot even start
# its nightly run several nights in a row, and a human unpauses it.
FAILURE_STREAK_PAUSE_THRESHOLD = 3
SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"
COORDINATOR_DISTINCT_ID = "context-layer-coordinator"
COMPLETED_TASK_RECOVERY_WINDOW = dt.timedelta(days=7)


def _capture_lane_event(distinct_id: str, event: str, properties: dict[str, str | int]) -> None:
    with ph_scoped_capture() as capture:
        capture(distinct_id=distinct_id, event=event, properties=properties)


@frozen
class DreamCoordinatorInput:
    pass


@frozen
class DreamCoordinatorOutput:
    planned: int
    dispatched: int
    failed: int


@frozen
class DispatchDreamRunInput:
    organization_id: str


@frozen
class DispatchDreamRunOutput:
    dispatched: bool


def _fetch_dream_candidates() -> list[str]:
    today = timezone.now().date()
    candidates: list[str] = []
    # Least-recently-dreamt first (never-dreamt before that): when more orgs are
    # due than the cap, the cap rotates through the fleet instead of permanently
    # starving whoever sorts last.
    for config in ContextLayerConfig.objects.filter(dreaming_paused=False).order_by(
        F("last_dream_started_at").asc(nulls_first=True), "created_at"
    ):
        if config.last_dream_started_at is not None and config.last_dream_started_at.date() >= today:
            continue
        organization_id = str(config.organization_id)
        if not context_layer_facade.is_context_layer_enabled(
            organization_id=organization_id, distinct_id=organization_id
        ):
            continue
        candidates.append(organization_id)
        if len(candidates) >= DISPATCH_CAP_PER_TICK:
            logger.warning("context_layer.dreaming.dispatch_cap_reached", cap=DISPATCH_CAP_PER_TICK)
            _capture_lane_event(
                COORDINATOR_DISTINCT_ID,
                "context layer dream dispatch cap reached",
                {"cap": DISPATCH_CAP_PER_TICK},
            )
            break
    return candidates


@activity.defn
async def fetch_dream_candidates() -> list[str]:
    """Organizations due a dream tonight: wiki exists, lane not paused, no
    dream started today, and the flag still on."""
    return await sync_to_async(_fetch_dream_candidates, thread_sensitive=False)()


@frozen
class _DreamDispatchTarget:
    config: ContextLayerConfig
    team_id: int
    user_id: int


def _prepare_dispatch(organization_id: str) -> _DreamDispatchTarget | None:
    config = ContextLayerConfig.objects.filter(organization_id=organization_id).first()
    if config is None or config.dreaming_paused:
        return None
    home_team = Team.objects.filter(organization_id=organization_id).order_by("id").first()
    user_id = config.created_by_id
    if home_team is None or user_id is None:
        logger.warning(
            "context_layer.dreaming.no_dispatch_target",
            organization_id=organization_id,
            has_team=home_team is not None,
        )
        # A lane that cannot even name a dispatch target counts as a failed
        # dispatch: without this it would retry silently every night forever
        # instead of tripping the circuit breaker for a human to look at.
        _record_dispatch_failure(config)
        _capture_lane_event(
            organization_id,
            "context layer dream dispatch failed",
            {"organization_id": organization_id, "reason": "no_dispatch_target"},
        )
        return None
    return _DreamDispatchTarget(config=config, team_id=home_team.id, user_id=user_id)


def _record_dispatch_success(config: ContextLayerConfig) -> None:
    ContextLayerConfig.objects.filter(pk=config.pk).update(last_dream_started_at=timezone.now(), dream_failure_streak=0)


def _record_dispatch_failure(config: ContextLayerConfig) -> None:
    streak = config.dream_failure_streak + 1
    # Pause on every full threshold of consecutive failures, not once past it:
    # a manually unpaused lane (streak left at the old value) gets a fresh
    # threshold of attempts before re-pausing instead of re-tripping on one.
    pause = streak % FAILURE_STREAK_PAUSE_THRESHOLD == 0
    ContextLayerConfig.objects.filter(pk=config.pk).update(
        dream_failure_streak=streak,
        dreaming_paused=pause,
    )
    if pause:
        logger.warning(
            "context_layer.dreaming.lane_paused",
            organization_id=str(config.organization_id),
            streak=streak,
        )
        _capture_lane_event(
            str(config.organization_id),
            "context layer dreaming paused",
            {"organization_id": str(config.organization_id), "streak": streak},
        )


@activity.defn
async def dispatch_dream_run(input: DispatchDreamRunInput) -> DispatchDreamRunOutput:
    """Start one org's nightly dream as a normal cloud task. Never raises:
    failures bump the org's streak and pause the lane at the threshold."""
    from products.context_layer.backend.enablement import (  # noqa: PLC0415 — avoids the enablement/Temporal import cycle
        import_channel_context,
    )
    from products.tasks.backend.facade.agents import (  # noqa: PLC0415 because the heavy sandbox stack should load only when a dream dispatches
        CustomPromptSandboxContext,
        create_task_and_trigger,
    )

    target = await sync_to_async(_prepare_dispatch, thread_sensitive=False)(input.organization_id)
    if target is None:
        return DispatchDreamRunOutput(dispatched=False)

    try:
        await sync_to_async(import_channel_context, thread_sensitive=False)(input.organization_id)
        # Read the previous night's stamp before _record_dispatch_success
        # overwrites it: it starts the activity window this dream reviews.
        previous_dream_started_at = target.config.last_dream_started_at
        await create_task_and_trigger(
            _build_dream_prompt(previous_dream_started_at),
            # Read-only MCP surface: the dream gathers from reads and lands its
            # branch through the commits endpoint, which accepts the run token's
            # task:write + internal_run:read pair — it never needs user-facing writes.
            # ACP carries that MCP surface and the publish environment into tool shells.
            CustomPromptSandboxContext(
                team_id=target.team_id,
                user_id=target.user_id,
                posthog_mcp_scopes="read_only",
                runtime="acp",
                runtime_adapter="codex",
                model="gpt-5.6-sol",
                reasoning_effort="high",
                initial_permission_mode="bypassPermissions",
            ),
            step_name="context-layer-dream",
            internal=True,
            workflow_id_prefix="context-layer-dream",
        )
    except Exception:
        logger.exception("context_layer.dreaming.dispatch_failed", organization_id=input.organization_id)
        await sync_to_async(_record_dispatch_failure, thread_sensitive=False)(target.config)
        await sync_to_async(_capture_lane_event, thread_sensitive=False)(
            input.organization_id,
            "context layer dream dispatch failed",
            {"organization_id": input.organization_id, "reason": "dispatch_error"},
        )
        return DispatchDreamRunOutput(dispatched=False)

    await sync_to_async(_record_dispatch_success, thread_sensitive=False)(target.config)
    await sync_to_async(_capture_lane_event, thread_sensitive=False)(
        input.organization_id,
        "context layer dream dispatched",
        {"organization_id": input.organization_id},
    )
    return DispatchDreamRunOutput(dispatched=True)


def _build_dream_prompt(since: dt.datetime | None) -> str:
    """The activity window this dream should review, then the canonical skills:
    synthesis first, then the bounded consolidation pass on the same branch."""
    if since is None:
        preamble = (
            "This is the first dream: review the last 7 days of organizational activity. "
            "Treat this as a seed run: include public Space pages that still have no substantive content, "
            "and fill them only when their channels have qualifying activity in the seed window."
        )
    else:
        since_utc = since.astimezone(dt.UTC)
        recovery_cutoff = since_utc - COMPLETED_TASK_RECOVERY_WINDOW
        preamble = (
            f"Review organizational activity since {since_utc.isoformat()}. "
            f"For completed tasks, recover from {recovery_cutoff.isoformat()} so work that completed after an "
            "earlier review is reconsidered."
        )
    return f"{preamble}\n\n{_dream_skills_content()}"


@functools.cache
def _dream_skills_content() -> str:
    """The canonical skills, verbatim. Cached because the checked-in files
    cannot change within a process's lifetime."""
    dreaming = (SKILLS_DIR / "context-layer-dreaming" / "SKILL.md").read_text(encoding="utf-8")
    consolidation = (SKILLS_DIR / "context-layer-consolidation" / "SKILL.md").read_text(encoding="utf-8")
    health_check = (SKILLS_DIR / "context-layer-health-check" / "SKILL.md").read_text(encoding="utf-8")
    return "\n\n".join(
        (_strip_frontmatter(dreaming), _strip_frontmatter(consolidation), _strip_frontmatter(health_check))
    )


def _strip_frontmatter(content: str) -> str:
    if not content.startswith("---"):
        return content
    _, _, rest = content.partition("---\n")
    _, _, body = rest.partition("---\n")
    return body.lstrip("\n")


@temporalio.workflow.defn(name="context-layer-dream-coordinator")
class ContextLayerDreamCoordinatorWorkflow(PostHogWorkflow):
    inputs_cls = DreamCoordinatorInput
    inputs_optional = True

    @temporalio.workflow.run
    async def run(self, input: DreamCoordinatorInput) -> DreamCoordinatorOutput:
        candidates = await temporalio.workflow.execute_activity(
            fetch_dream_candidates,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )
        # Dispatches run concurrently so the coordinator's lifetime stays far
        # below the nightly tick; the worker's activity concurrency throttles.
        # return_exceptions so one dispatch raising (an ORM error outside the
        # activity's try, or the server-enforced activity timeout) can't sink
        # the other orgs' dreams; each unstamped lane requalifies tomorrow.
        results = await asyncio.gather(
            *(
                temporalio.workflow.execute_activity(
                    dispatch_dream_run,
                    DispatchDreamRunInput(organization_id=organization_id),
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
                )
                for organization_id in candidates
            ),
            return_exceptions=True,
        )
        dispatched = 0
        for organization_id, result in zip(candidates, results):
            # A captured cancellation must propagate, not read as a lane failure.
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                temporalio.workflow.logger.warning(
                    "context-layer dream dispatch raised",
                    extra={"organization_id": organization_id, "error": str(result)},
                )
                continue
            if result.dispatched:
                dispatched += 1
        return DreamCoordinatorOutput(
            planned=len(candidates), dispatched=dispatched, failed=len(candidates) - dispatched
        )


@temporalio.workflow.defn(name="context-layer-bootstrap-dream")
class ContextLayerBootstrapDreamWorkflow(PostHogWorkflow):
    @temporalio.workflow.run
    async def run(self, input: DispatchDreamRunInput) -> DispatchDreamRunOutput:
        return await temporalio.workflow.execute_activity(
            dispatch_dream_run,
            input,
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
        )


def trigger_bootstrap_dream(organization_id: str) -> None:
    """Fire-and-forget first dream. Enablement remains successful if Temporal is unavailable."""
    try:
        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                "context-layer-bootstrap-dream",
                DispatchDreamRunInput(organization_id=organization_id),
                id=f"context-layer-bootstrap-dream-{organization_id}-{uuid.uuid4()}",
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
        )
    except Exception:
        logger.exception("context_layer.dreaming.bootstrap_dispatch_failed", organization_id=organization_id)
        config = ContextLayerConfig.objects.filter(organization_id=organization_id).first()
        if config is not None:
            _record_dispatch_failure(config)
