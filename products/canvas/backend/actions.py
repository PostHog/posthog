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

import structlog
import posthoganalytics
from rest_framework import serializers

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models import Team

    from products.canvas.backend.models import Canvas

logger = structlog.get_logger(__name__)

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
    ]
}
