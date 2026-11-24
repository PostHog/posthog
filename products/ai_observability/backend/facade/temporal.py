"""Facade re-export for the AI observability Temporal surface.

The worker registers ``WORKFLOWS``/``ACTIVITIES`` on the LLMA task queue. Isolated from ``facade/api.py`` so the
workflow sandbox imports never land on the web request path.
"""

from django.conf import settings

from posthog.cloud_utils import is_cloud
from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.ai_observability.backend.temporal.eval_suggestions_client import (
    SCHEDULE_ID as EVAL_SUGGESTIONS_SCHEDULE_ID,
    create_eval_suggestions_schedule,
)
from products.ai_observability.backend.temporal.registry import ACTIVITIES, WORKFLOWS

__all__ = ["ACTIVITIES", "EVAL_SUGGESTIONS_SCHEDULE_ID", "WORKFLOWS", "create_eval_suggestions_schedule"]

TEMPORAL = TemporalRegistration(
    queues=(QueueBinding(queue_setting="LLMA_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)),),
    schedules=(create_eval_suggestions_schedule,) if settings.DEBUG or is_cloud() else (),
)
