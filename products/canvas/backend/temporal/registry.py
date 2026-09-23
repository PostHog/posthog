"""Workflow and activity registration lists for the canvas build Temporal worker.

Stable import target for the worker wiring:
``from products.canvas.backend.temporal.registry import WORKFLOWS, ACTIVITIES``.
Imported directly (like ``backend.tasks`` for Celery) because canvas is not an
isolated product yet; once it is, this moves behind ``facade/temporal.py``.
"""

from __future__ import annotations

from products.canvas.backend.temporal.activities import run_canvas_build_activity
from products.canvas.backend.temporal.workflow import CanvasBuildWorkflow

WORKFLOWS = [CanvasBuildWorkflow]

ACTIVITIES = [run_canvas_build_activity]

__all__ = ["WORKFLOWS", "ACTIVITIES"]
