"""Declared canvas operations: named entry points to action verbs that agents call by name.

An operation lives in the live version's ``capabilities.posthog.operations``. It binds one declared
verb to a fixed payload plus the ``inputs`` a caller may supply, so an agent (through MCP) or a
team skill can run "enable-beta" without knowing the verb's payload shape. Invocation reuses the
action pipeline: the same validation, the same viewer identity, the same kill switch.
"""

import re
from typing import Any
from uuid import UUID

from rest_framework import status

from products.canvas.backend.actions import CANVAS_ACTIONS
from products.canvas.backend.facade.contracts import CanvasRecord, CanvasRequestRejected
from products.canvas.backend.logic.canvases import canvas_row
from products.canvas.backend.models import Canvas

SKILL_NAME_PREFIX = "canvas-"
MAX_SKILL_NAME_LENGTH = 64
MAX_SKILL_DESCRIPTION_LENGTH = 400
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def declared_operations(capabilities: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [
        operation
        for operation in ((capabilities or {}).get("posthog") or {}).get("operations") or []
        if isinstance(operation, dict) and operation.get("verb") in CANVAS_ACTIONS
    ]


def list_operations(capabilities: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Each declared operation with the registry metadata of its verb."""
    rows = []
    for operation in declared_operations(capabilities):
        entry = CANVAS_ACTIONS[operation["verb"]]
        rows.append(
            {
                "name": operation["name"],
                "description": operation.get("description", ""),
                "verb": entry.verb,
                "inputs": list(operation.get("inputs") or []),
                "destructive": entry.destructive,
                "starts_cloud_run": entry.starts_cloud_run,
                "required_scopes": ["canvas:write", *entry.required_scopes],
            }
        )
    return rows


def find_operation(capabilities: dict[str, Any] | None, name: str) -> dict[str, Any] | None:
    return next((operation for operation in declared_operations(capabilities) if operation.get("name") == name), None)


def operation_verb(team_id: int, canvas_id: UUID | str, name: str) -> str | None:
    """The verb the canvas's live version binds to this operation, or None when there is no such operation."""
    try:
        canvas = canvas_row(team_id, canvas_id)
    except Canvas.DoesNotExist:
        return None
    version = canvas.current_source_version
    operation = find_operation(version.capabilities if version else None, name)
    return operation["verb"] if operation is not None else None


def operation_verb_required_scopes(verb: str | None) -> list[str] | None:
    """The scopes a scoped credential needs to run an operation bound to ``verb``."""
    if verb is None:
        return None
    return ["canvas:write", *CANVAS_ACTIONS[verb].required_scopes]


def operation_required_scopes(team_id: int, canvas_id: UUID | str, name: str) -> list[str] | None:
    """The scopes a scoped credential needs for this operation, or None when the canvas has no such operation."""
    return operation_verb_required_scopes(operation_verb(team_id, canvas_id, name))


def operation_payload(operation: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """The verb payload for one invocation: the declared payload plus the caller's inputs.

    A caller cannot replace a fixed payload field, even when an older declaration also lists it in inputs.
    """
    fixed = operation.get("payload") or {}
    allowed = set(operation.get("inputs") or []) - set(fixed)
    unexpected = sorted(set(arguments) - allowed)
    if unexpected:
        raise CanvasRequestRejected(
            status.HTTP_400_BAD_REQUEST,
            f'Operation "{operation["name"]}" accepts only {sorted(allowed) or "no"} arguments; '
            f"got {', '.join(unexpected)}.",
        )
    return {**fixed, **arguments}


def operation_skill_owner(canvas: CanvasRecord) -> dict[str, str]:
    """The skill metadata that marks a skill as this canvas's operations skill."""
    return {"canvas_id": str(canvas.id), "source": "canvas_operations"}


def operation_skill_name(canvas: CanvasRecord) -> str:
    """The name for a canvas's first operations skill: the slugged canvas name plus a short id.

    The name is set once. A later publish finds the skill by its owner metadata, so a rename keeps it.
    """
    slug = _SLUG_RE.sub("-", canvas.name.lower()).strip("-") or "canvas"
    suffix = str(canvas.id).replace("-", "")[:8]
    budget = MAX_SKILL_NAME_LENGTH - len(SKILL_NAME_PREFIX) - len(suffix) - 1
    return f"{SKILL_NAME_PREFIX}{slug[:budget].rstrip('-')}-{suffix}"


def operation_skill_description(canvas: CanvasRecord, operations: list[dict[str, Any]]) -> str:
    names = ", ".join(operation["name"] for operation in operations)
    description = f'Run the operations of the PostHog canvas "{canvas.name}" ({names}) as the current user.'
    return description[: MAX_SKILL_DESCRIPTION_LENGTH - 1] + (
        "…" if len(description) >= MAX_SKILL_DESCRIPTION_LENGTH else ""
    )


def operation_skill_body(canvas: CanvasRecord, operations: list[dict[str, Any]], canvas_url: str) -> str:
    """The SKILL.md body: what each operation does and the exact MCP calls that run it."""
    lines = [
        f"# {canvas.name}: operations",
        "",
        f"The canvas [{canvas.name}]({canvas_url}) (id `{canvas.id}`) declares the operations below. Each one",
        "runs a PostHog write as the current user, with their own permissions; nothing runs as the canvas author.",
        "",
        "## How to run one",
        "",
        "1. Call `canvas-operations-list` with `id` set to the canvas id to confirm the operation still exists",
        "   and read its current `inputs`; the live version may have changed since this skill was published.",
        "2. Call `canvas-operation-invoke` with `id`, `operation_name`, and `arguments` holding exactly the",
        "   declared inputs. An argument outside `inputs` is refused.",
        "3. Report the returned `result` to the user. A 409 with `change_request_id` means an approval policy",
        "   took the change; say it was sent for approval.",
        "",
        "Operations marked destructive disable or stop something: confirm with the user before invoking them.",
        "",
        "## Operations",
        "",
    ]
    for operation in operations:
        inputs = ", ".join(f"`{key}`" for key in operation["inputs"]) or "none"
        flags = []
        if operation["destructive"]:
            flags.append("destructive")
        if operation["starts_cloud_run"]:
            flags.append("starts paid compute")
        suffix = f" ({', '.join(flags)})" if flags else ""
        lines.append(f"### `{operation['name']}`{suffix}")
        lines.append("")
        lines.append(operation["description"])
        lines.append("")
        lines.append(f"- Verb: `{operation['verb']}`")
        lines.append(f"- Inputs: {inputs}")
        lines.append(f"- Scopes for an API key: {', '.join(f'`{scope}`' for scope in operation['required_scopes'])}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
