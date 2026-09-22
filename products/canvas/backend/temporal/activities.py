"""Temporal activity for running one canvas build.

The activity is a thin wrapper over ``build_service.run_canvas_build``, which owns the
whole build lifecycle (claiming, lease renewal, terminal states) and is idempotent:
finished builds are a no-op, so activity retries and duplicate deliveries are safe.
"""

from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.utils import asyncify


@frozen
class CanvasBuildInput:
    team_id: int
    build_id: str


@activity.defn
@asyncify
def run_canvas_build_activity(input: CanvasBuildInput) -> None:
    from products.canvas.backend.build_service import (  # noqa: PLC0415 — keeps the heavy build service off the import path
        run_canvas_build,
    )

    run_canvas_build(input.team_id, input.build_id)
