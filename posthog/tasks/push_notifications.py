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
from posthog.scoping_audit import skip_team_scope_audit

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
@skip_team_scope_audit
def send_user_push(
    user_id: int,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    suppressed_push_token_ids: list[str] | None = None,
) -> None:
    """Fan out a push notification to every device registered for ``user_id``.

    User push tokens are user-scoped, not team-scoped, so this task intentionally
    operates outside the team-scoping audit. The downstream ``send_push_to_user``
    helper filters tokens by ``user=user`` — there is no cross-team query happening.

    ``suppressed_push_token_ids`` (UUIDs of ``UserPushToken`` rows) are dropped
    from the fanout, so callers can pre-compute a "skip these devices" set —
    e.g. devices whose presence beacon says they're already watching the task
    that triggered this push.
    """
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.warning("send_user_push.user_not_found", user_id=user_id)
        return

    try:
        send_push_to_user(
            user,
            title=title,
            body=body,
            data=data,
            suppressed_push_token_ids=suppressed_push_token_ids,
        )
    except Exception:
        logger.warning("send_user_push.failed", user_id=user_id, exc_info=True)
