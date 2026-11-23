"""Workflow and activity registration lists for the canvas build Temporal worker.

Core reaches these through ``facade/temporal.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from products.canvas.backend.temporal.activities import run_canvas_build_activity
from products.canvas.backend.temporal.workflow import CanvasBuildWorkflow

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS = [CanvasBuildWorkflow]

ACTIVITIES: list[ActivityDefinition] = [run_canvas_build_activity]

__all__ = ["WORKFLOWS", "ACTIVITIES"]
