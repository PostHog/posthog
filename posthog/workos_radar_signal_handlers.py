"""Reports a password login to WorkOS Radar when the session signs in, which is after any second factor."""

from typing import Any, Optional

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.http import HttpRequest

RADAR_LOGIN_ATTEMPT_SESSION_KEY = "radar_login_attempt"


def remember_login_attempt(request: HttpRequest, attempt_id: str, user_pk: int) -> None:
    """Keep the attempt of a correct password until the session signs in as that user."""
    request.session[RADAR_LOGIN_ATTEMPT_SESSION_KEY] = {"attempt_id": attempt_id, "user_pk": user_pk}


@receiver(user_logged_in)
def report_radar_login_success(sender: Any, user: Any, request: Optional[HttpRequest] = None, **kwargs: Any) -> None:
    session = getattr(request, "session", None)
    if session is None:
        return
    pending = session.pop(RADAR_LOGIN_ATTEMPT_SESSION_KEY, None)
    if not isinstance(pending, dict) or pending.get("user_pk") != user.pk:
        return
    # posthog.tasks imports every task module, so it loads at a login that has an attempt, not at startup
    from posthog.tasks.workos_radar import queue_attempt_success  # noqa: PLC0415

    queue_attempt_success(str(pending.get("attempt_id") or ""))
