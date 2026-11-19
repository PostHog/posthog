"""Workflow and activity registration lists for the canvas build Temporal worker.

Core reaches these through ``facade/temporal.py``.
"""

from __future__ import annotations

from collections.abc import Callable

from products.canvas.backend.temporal.activities import run_canvas_build_activity
from products.canvas.backend.temporal.workflow import CanvasBuildWorkflow

WORKFLOWS = [CanvasBuildWorkflow]

ACTIVITIES: list[Callable[..., object]] = [run_canvas_build_activity]

__all__ = ["WORKFLOWS", "ACTIVITIES"]
