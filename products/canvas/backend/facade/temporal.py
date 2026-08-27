"""Facade re-export for the canvas Temporal surface.

The worker registers ``WORKFLOWS``/``ACTIVITIES`` for the canvas build task queue.
Isolated from ``facade/api.py`` so ``temporalio`` never lands on the light data-surface
import path.
"""

from products.canvas.backend.temporal.registry import ACTIVITIES, WORKFLOWS

__all__ = ["ACTIVITIES", "WORKFLOWS"]
