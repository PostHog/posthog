"""Celery task wrapper around the synchronous Expo push helper.

The helper does sync ``requests.post`` with a 10-second timeout — fine in a
worker, dangerous inside a request/response cycle or an async Temporal
activity. Schedule this task via ``transaction.on_commit(lambda: …delay(…))``
to dispatch pushes off the hot path.
"""

from __future__ import annotations

from typing import Any

import structlog
from celery import shared_task

from posthog.models.user import User
from posthog.push_notifications import send_push_to_user

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def send_user_push(user_id: int, title: str, body: str, data: dict[str, Any] | None = None) -> None:
    """Fan out a push notification to every device registered for ``user_id``."""
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.warning("send_user_push.user_not_found", user_id=user_id)
        return

    try:
        send_push_to_user(user, title=title, body=body, data=data)
    except Exception:
        logger.warning("send_user_push.failed", user_id=user_id, exc_info=True)
