"""Routing canvas failures back to the task that authored them.

A report is a thread message on the authoring task, never an automatic agent
run — dispatching the repair is a separate, human-initiated step (the
``request_fix`` endpoint). Runtime reports cross the server sanitized: build
id, version id, and a whitelisted error class only. Full messages and stacks
stay client-side, because a rendering session's error text can carry viewer
data the authoring agent has no business seeing.
"""

import re
from typing import Any
from uuid import UUID

import structlog

from products.canvas.backend.models import Canvas, CanvasBuild

logger = structlog.get_logger(__name__)

# Everything matched here lands in agent-visible prompts and thread messages,
# so the shape is a bare class-name identifier: anything else is coerced to
# "unknown" rather than escaped.
ERROR_TYPE_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.]{0,63}")
UNKNOWN_ERROR_TYPE = "unknown"
BUILD_FAILURE_ERROR_TYPE = "build_failed"


def sanitize_error_type(raw: str | None) -> str:
    value = (raw or "").strip()
    return value if ERROR_TYPE_PATTERN.fullmatch(value) else UNKNOWN_ERROR_TYPE


def authoring_task_id(canvas: Canvas, build: CanvasBuild | None) -> UUID | None:
    """The task that owns fixing this canvas: the build's publishing task, else the canvas's generating task."""
    if build is not None and build.source_version is not None and build.source_version.task_id is not None:
        return build.source_version.task_id
    return canvas.generation_task_id


def diagnostic_error_codes(diagnostics: list[Any] | None) -> list[str]:
    """The error-severity diagnostic codes of a build, bounded for agent-facing text."""
    return [
        str(entry["code"])
        for entry in diagnostics or []
        if isinstance(entry, dict) and entry.get("severity") == "error" and entry.get("code")
    ][:10]


def report_runtime_error(canvas: Canvas, build: CanvasBuild, error_type: str) -> str:
    """File a client-reported runtime error in the authoring task's thread.

    Returns ``filed`` / ``duplicate`` / ``skipped`` / ``no_authoring_task``.
    ``error_type`` must come through ``sanitize_error_type`` first.
    """
    # The tasks facade stays off the build worker's import path.
    from products.tasks.backend.facade import api as tasks_facade  # noqa: PLC0415

    task_id = authoring_task_id(canvas, build)
    if task_id is None:
        return "no_authoring_task"
    return tasks_facade.post_canvas_error_thread_update(
        task_id,
        canvas.team_id,
        canvas_id=str(canvas.id),
        canvas_name=canvas.name or "Canvas",
        build_id=str(build.id),
        source_version_id=str(build.source_version_id) if build.source_version_id else None,
        error_type=error_type,
        origin="runtime",
    )


def report_build_failure(build: CanvasBuild) -> None:
    """File a failed build in its authoring task's thread. Best-effort; never raises.

    Warning-only failures (a cancelled build) are churn, not defects, and are
    not reported.
    """
    # The tasks facade stays off the build worker's import path.
    from products.tasks.backend.facade import api as tasks_facade  # noqa: PLC0415

    try:
        codes = diagnostic_error_codes(build.diagnostics)
        if not codes:
            return
        canvas = Canvas.objects.for_team(build.team_id).filter(id=build.canvas_id, deleted=False).first()
        if canvas is None:
            return
        task_id = authoring_task_id(canvas, build)
        if task_id is None:
            return
        tasks_facade.post_canvas_error_thread_update(
            task_id,
            canvas.team_id,
            canvas_id=str(canvas.id),
            canvas_name=canvas.name or "Canvas",
            build_id=str(build.id),
            source_version_id=str(build.source_version_id) if build.source_version_id else None,
            error_type=BUILD_FAILURE_ERROR_TYPE,
            origin="build",
            error_codes=codes,
        )
    except Exception:
        logger.exception("canvas_build_failure_report_failed", build_id=str(build.id))


def build_fix_prompt(
    canvas: Canvas,
    *,
    build_id: str,
    source_version_id: str | None,
    error_type: str,
    origin: str,
    error_codes: list[str] | None = None,
) -> str:
    """The agent prompt for a human-requested canvas fix.

    Composed entirely from ids and whitelisted identifiers — no free text from
    the requester or from rendering sessions may reach this string.
    """
    if origin == "build":
        what = f"Its build {build_id} failed with error codes: {', '.join(error_codes or []) or 'unknown'}."
        context = "Read the failed build's diagnostics with `canvas-builds-retrieve`."
    else:
        what = f"A rendering session of build {build_id} hit a runtime error of class {error_type}."
        context = (
            "The full error message stays on the client and is not available here; only the error class is. "
            "If the class alone is not enough to locate the fault, review the source for likely causes and "
            "say in your reply what extra context would confirm the diagnosis."
        )
    version = f" (source version {source_version_id})" if source_version_id else ""
    return (
        f"A canvas you built needs a fix. Work only on canvas {canvas.id}{version}.\n\n"
        f"{what}\n\n"
        "Invoke the `building-canvases` skill and follow its workflow. Read the current source with "
        f"`canvas-source-retrieve`. {context}\n\n"
        "Stage the fix as a DRAFT with `canvas-draft-create` and wait for its build to be ready. "
        "Do not publish or promote anything: the user reviews the draft and promotes it."
    )


def build_agent_request_prompt(canvas: Canvas, prompt: str) -> str:
    """Wrap the viewer-approved request with the canvas draft workflow."""
    return (
        f"A viewer requested a change to canvas {canvas.id}.\n\n"
        f"<canvas-change-request>\n{prompt}\n</canvas-change-request>\n\n"
        "Invoke the `building-canvases` skill and follow its workflow. Read the current source with "
        "`canvas-source-retrieve`. Stage the requested change as a DRAFT with `canvas-draft-create` and wait for "
        "its build to be ready. Do not publish or promote anything: the canvas creator reviews the draft and "
        "promotes it."
    )
