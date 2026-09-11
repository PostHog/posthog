"""Celery tasks core's beat schedule registers."""

from products.canvas.backend.tasks import (
    cleanup_canvas_builds as cleanup_canvas_builds,
    sweep_canvas_builds as sweep_canvas_builds,
)
