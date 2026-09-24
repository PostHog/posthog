"""Canvas action registry: the PostHog writes a canvas may invoke (ph.actions).

One pipeline serves every verb: the host forwards ph.actions.invoke(verb,
payload) to the invoke endpoint, which checks the canvas's declared
capabilities, validates the payload against the verb's serializer, and
executes as the viewer — the server re-checks the viewer's own permissions,
exactly as if they acted in the app. Adding a verb is a registry entry, not a
design. Verbs that delete or disable set ``destructive=True``, which the host
renders as an explicit confirm before invoking.

Executors import their product facades lazily so this module stays cheap on
the source-validation import path (the builder imports it for verb names).
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from django.db import transaction

import structlog
import posthoganalytics
from rest_framework import serializers

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from rest_framework.response import Response

    from posthog.models import Team

    from products.canvas.backend.models import Canvas

logger = structlog.get_logger(__name__)


class CanvasActionDenied(Exception):
    def __init__(self, response: "Response") -> None:
        super().__init__(str(response.data))
        self.response = response


# Kill switch: enabling this flag for a team turns every action verb off at
# once. Evaluation failure leaves actions on — the switch is for emergencies,
# not a gate normal traffic should wait on.
CANVAS_ACTIONS_KILL_SWITCH_FLAG = "canvas-actions-disabled"


def canvas_actions_disabled(team: "Team") -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                CANVAS_ACTIONS_KILL_SWITCH_FLAG,
                str(team.uuid),
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("canvas_actions_kill_switch_check_failed")
        return False


class AnnotationCreatePayloadSerializer(serializers.Serializer):
    """Payload for the annotations.create verb."""

    content = serializers.CharField(max_length=1024, help_text="The annotation text.")
    date_marker = serializers.DateTimeField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Point in time the annotation marks. Omit to mark the moment it was created.",
    )


class TaskCreatePayloadSerializer(serializers.Serializer):
    """Payload for the tasks.create verb."""

    title = serializers.CharField(max_length=255, help_text="Task title (max 255 characters, matching the task store).")
    description = serializers.CharField(
        allow_blank=True, default="", help_text="Task description (markdown), passed to the agent that picks it up."
    )


class TaskCreateAndRunPayloadSerializer(TaskCreatePayloadSerializer):
    idempotency_key = serializers.UUIDField(help_text="Reuse this UUID when retrying the same cloud task request.")
    model = serializers.CharField(
        required=False, max_length=255, help_text="Task model identifier. Omit to use the viewer's default model."
    )
    reasoning_effort = serializers.CharField(
        required=False, max_length=32, help_text="Reasoning effort supported by the selected model. Requires model."
    )


class WorkflowIdsPayloadSerializer(serializers.Serializer):
    """Payload for the workflows.pause and workflows.resume verbs."""

    workflow_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=20,
        help_text="The workflows to change, all in this project.",
    )


def _set_workflows_enabled(team_id: int, user_id: int, payload: dict[str, Any], *, enabled: bool) -> dict[str, Any]:
    from rest_framework import status as http_status  # noqa: PLC0415
    from rest_framework.response import Response  # noqa: PLC0415

    from products.workflows.backend.facade import api as workflows_facade  # noqa: PLC0415 — load on execute

    with transaction.atomic():
        changed = []
        for workflow_id in payload["workflow_ids"]:
            try:
                new_status = workflows_facade.set_workflow_enabled(
                    team_id=team_id, user_id=user_id, workflow_id=workflow_id, enabled=enabled
                )
            except workflows_facade.WorkflowNotFound:
                raise CanvasActionDenied(
                    Response(
                        {"detail": f"Workflow {workflow_id} is not in this project."},
                        status=http_status.HTTP_404_NOT_FOUND,
                    )
                )
            except workflows_facade.WorkflowAccessDenied:
                raise CanvasActionDenied(
                    Response(
                        {"detail": f"You cannot edit workflow {workflow_id}."}, status=http_status.HTTP_403_FORBIDDEN
                    )
                )
            except workflows_facade.WorkflowArchived:
                raise CanvasActionDenied(
                    Response(
                        {"detail": f"Workflow {workflow_id} is archived and cannot be changed."},
                        status=http_status.HTTP_409_CONFLICT,
                    )
                )
            changed.append({"id": str(workflow_id), "status": new_status})
    return {"workflows": changed}


def _pause_workflows(team_id: int, user_id: int, canvas: "Canvas", payload: dict[str, Any]) -> dict[str, Any]:
    return _set_workflows_enabled(team_id, user_id, payload, enabled=False)


def _resume_workflows(team_id: int, user_id: int, canvas: "Canvas", payload: dict[str, Any]) -> dict[str, Any]:
    return _set_workflows_enabled(team_id, user_id, payload, enabled=True)


def _create_annotation(team_id: int, user_id: int, canvas: "Canvas", payload: dict[str, Any]) -> dict[str, Any]:
    from products.annotations.backend.facade import api as annotations_facade  # noqa: PLC0415 — load on execute

    annotation_id = annotations_facade.create_project_annotation(
        team_id, user_id, content=payload["content"], date_marker=payload.get("date_marker")
    )
    return {"annotation_id": annotation_id}


def _create_task(team_id: int, user_id: int, canvas: "Canvas", payload: dict[str, Any]) -> dict[str, Any]:
    from products.tasks.backend.facade import api as tasks_facade  # noqa: PLC0415 — load on execute

    task_id = tasks_facade.create_channel_task(
        team_id, user_id, canvas.channel_id, title=payload["title"], description=payload["description"]
    )
    return {"task_id": str(task_id)}


def _create_and_run_task(team_id: int, user_id: int, canvas: "Canvas", payload: dict[str, Any]) -> dict[str, Any]:
    from posthog.models.user import User  # noqa: PLC0415

    from products.tasks.backend.facade.access import usage_limit_response  # noqa: PLC0415
    from products.tasks.backend.facade.canvas_tasks import (  # noqa: PLC0415 - keeps task runtime imports off canvas validation
        create_and_run_channel_task,
    )

    def check_usage() -> None:
        if response := usage_limit_response(User.objects.get(id=user_id), team_id):
            raise CanvasActionDenied(response)

    run = create_and_run_channel_task(
        team_id,
        user_id,
        canvas.channel_id,
        canvas_id=canvas.id,
        title=payload["title"],
        description=payload["description"],
        idempotency_key=payload["idempotency_key"],
        before_create=check_usage,
        model=payload.get("model"),
        reasoning_effort=payload.get("reasoning_effort"),
    )
    return {"task_id": str(run.task_id), "run_id": str(run.id), "status": run.status}


@frozen
class CanvasAction:
    """One verb of the registry: what it does, its payload shape, and how loudly the host must ask."""

    verb: str
    summary: str
    destructive: bool
    payload_serializer: type[serializers.Serializer]
    execute: Callable[[int, int, "Canvas", dict[str, Any]], dict[str, Any]]
    # API scopes a scoped credential (personal API key, OAuth token) must hold
    # to invoke this verb — the target resource's write scope, so canvas:write
    # alone never grants writes to other resources. Session users carry no
    # scopes and are unaffected.
    required_scopes: tuple[str, ...]
    # Authoring docs served through the registry endpoint: payload and result
    # shape, what actually happens, and the confirmation copy the verb
    # warrants. Agents build against the deployed registry rather than a skill
    # file, so a verb's docs ship (and stay current) with the verb itself.
    usage: str
    starts_cloud_run: bool = False


CANVAS_ACTIONS: dict[str, CanvasAction] = {
    action.verb: action
    for action in [
        CanvasAction(
            verb="annotations.create",
            summary="Create a project annotation.",
            destructive=False,
            payload_serializer=AnnotationCreatePayloadSerializer,
            execute=_create_annotation,
            required_scopes=("annotation:write",),
            usage=(
                "Payload `{content, date_marker?}` → result `{annotation_id}`. Creates a project "
                "annotation: a note pinned to a point in time, rendered as a marker on insight "
                "graphs and listed under Data management → Annotations. Pass `date_marker` (ISO "
                "timestamp) when the moment is not now — e.g. when an incident started, not when "
                "it was written down. `content` is capped at 1024 characters."
            ),
        ),
        CanvasAction(
            verb="tasks.create",
            summary="File a task in the canvas's channel, as the viewer.",
            destructive=False,
            payload_serializer=TaskCreatePayloadSerializer,
            execute=_create_task,
            required_scopes=("task:write",),
            usage=(
                "Payload `{title, description}` → result `{task_id}`. Files a bare task into the "
                "canvas's own channel, created by the viewer — it appears in the channel feed "
                "under their name. No agent run starts and no repository or run configuration is "
                "attached; the viewer opens it from the channel and drives it from there. Say that "
                'in the confirmation copy ("Task filed in this channel — open it to start work"), '
                'never "an agent is on it". Keep the title short and put full context in '
                "`description` (markdown) — whoever picks the task up sees only those two fields, "
                "not the canvas."
            ),
        ),
        CanvasAction(
            verb="tasks.create_and_run",
            summary="Create and start a cloud task in this space, with optional model settings.",
            destructive=False,
            payload_serializer=TaskCreateAndRunPayloadSerializer,
            execute=_create_and_run_task,
            required_scopes=("task:write",),
            starts_cloud_run=True,
            usage=(
                "Payload `{title, description?, idempotency_key, model?, reasoning_effort?}` returns "
                "`{task_id, run_id, status}`. "
                "Creates a task in the canvas's space as the viewer and queues its cloud run. "
                "Inherits the space's repositories and the viewer's default run settings. "
                "Optional model and reasoning_effort (from the task model catalogue) override those defaults for "
                "this task only; reasoning_effort requires model. "
                "The standard cloud access and usage limits apply. This action uses paid compute. "
                "Use a 'Start cloud task' button and disable it while the request is pending. "
                "Generate a UUID for idempotency_key once per intended task and reuse it on retries; "
                "a retry returns the existing task and latest run without starting another run. "
                "Use the returned status in the result message. A queued run has not finished. "
                "Declare this verb separately from tasks.create, which still creates a task without a run."
            ),
        ),
        CanvasAction(
            verb="workflows.pause",
            summary="Disable workflows in this project so they stop running.",
            destructive=True,
            payload_serializer=WorkflowIdsPayloadSerializer,
            execute=_pause_workflows,
            required_scopes=("hog_flow:write",),
            usage=(
                "Payload `{workflow_ids}` (1 to 20 workflow ids in this project) → result "
                "`{workflows: [{id, status}]}`. Sets each workflow's status to `draft`, the same "
                "change as disabling it in the Workflows product: a scheduled workflow stops at its "
                "next occurrence and an event-triggered one stops firing. Its schedule and content "
                "are kept, so `workflows.resume` restores it. The viewer must be able to edit each "
                "workflow; an id from another project fails the whole call. Destructive: the host asks "
                "the viewer to confirm. Use it for a pause switch on a board that owns a set of loops, "
                'with copy such as "Pause the loops in this space" and the returned statuses in the result.'
            ),
        ),
        CanvasAction(
            verb="workflows.resume",
            summary="Enable workflows in this project so they run again.",
            destructive=False,
            payload_serializer=WorkflowIdsPayloadSerializer,
            execute=_resume_workflows,
            required_scopes=("hog_flow:write",),
            usage=(
                "Payload `{workflow_ids}` (1 to 20 workflow ids in this project) → result "
                "`{workflows: [{id, status}]}`. Sets each workflow's status to `active`, the same "
                "change as enabling it in the Workflows product; a scheduled workflow fires again at its "
                "next occurrence. The viewer must be able to edit each workflow. Pair with "
                "`workflows.pause` behind one switch and reflect the returned statuses."
            ),
        ),
    ]
}
