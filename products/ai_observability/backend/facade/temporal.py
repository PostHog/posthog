"""Facade re-export for the AI observability Temporal surface.

The worker registers ``WORKFLOWS``/``ACTIVITIES`` on the LLMA task queue. Isolated from ``facade/api.py`` so the
workflow sandbox imports never land on the web request path.
"""

from products.ai_observability.backend.eval_suggestions.client import (
    SCHEDULE_ID as EVAL_SUGGESTIONS_SCHEDULE_ID,
    create_eval_suggestions_schedule,
)
from products.ai_observability.backend.temporal.registry import ACTIVITIES, WORKFLOWS

__all__ = ["ACTIVITIES", "EVAL_SUGGESTIONS_SCHEDULE_ID", "WORKFLOWS", "create_eval_suggestions_schedule"]
