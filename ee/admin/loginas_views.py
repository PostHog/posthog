import json
from typing import Optional

from django.contrib.admin.models import CHANGE, LogEntry
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_http_methods

import structlog
import posthoganalytics
from loginas.utils import is_impersonated_session
from loginas.views import user_login as loginas_user_login

from posthog.helpers.impersonation import get_impersonated_user, get_original_user_from_session
from posthog.middleware import (
    IMPERSONATION_READ_ONLY_SESSION_KEY,
    IMPERSONATION_REASON_SESSION_KEY,
    is_read_only_impersonation,
)
from posthog.models import User

logger = structlog.get_logger(__name__)


def _log_impersonation_mode_change(staff_user: User, target_user: Optional[User], reason: str, mode: str) -> None:
    """Record an impersonation upgrade/downgrade in the Django admin audit log.

    Mirrors how `loginas` records impersonation starts (a LogEntry against the target user,
    attributed to the original staff user) so mode changes share the same audit trail. Logging
    must never break the mode change itself.
    """
    if not target_user:
        return
    change_message = f"User {staff_user} changed impersonation of {target_user} to {mode}."
    if reason:
        change_message += f" Reason: {reason}"
    try:
        LogEntry.objects.log_actions(
            user_id=staff_user.pk,
            queryset=[target_user],
            change_message=change_message,
            action_flag=CHANGE,
        )
    except Exception:
        logger.exception("Failed to log impersonation mode change", mode=mode)


def loginas_user(request, user_id):
    staff_user = request.user
    response = loginas_user_login(request, user_id)

    if is_impersonated_session(request):
        is_read_only = request.POST.get("read_only") != "false"
        if is_read_only:
            request.session[IMPERSONATION_READ_ONLY_SESSION_KEY] = True

        # Persist the reason server-side so it survives both Django-admin and in-app starts,
        # and can be surfaced to the frontend (autofill) and the activity log.
        request.session[IMPERSONATION_REASON_SESSION_KEY] = request.POST.get("reason", "")

        target_user = User.objects.filter(id=user_id).first()
        posthoganalytics.capture(
            distinct_id=str(staff_user.distinct_id),
            event="impersonation_started",
            properties={
                "mode": "read_only" if is_read_only else "read_write",
                "reason": request.POST.get("reason", ""),
                "staff_user_id": staff_user.id,
                "staff_user_email": staff_user.email,
                "target_user_id": user_id,
                "target_user_email": target_user.email if target_user else None,
            },
        )

    return response


@require_http_methods(["POST"])
def upgrade_impersonation(request):
    """Upgrade from read-only to read-write impersonation"""
    if not is_impersonated_session(request) or not is_read_only_impersonation(request):
        raise Http404()

    try:
        data = json.loads(request.body)
        reason = data.get("reason", "").strip()
    except (json.JSONDecodeError, AttributeError):
        reason = ""

    if not reason:
        return JsonResponse({"error": "A reason is required to upgrade impersonation"}, status=400)

    staff_user = get_original_user_from_session(request)
    if not staff_user or not staff_user.is_staff:
        return JsonResponse({"error": "Unable to upgrade impersonation"}, status=400)

    if IMPERSONATION_READ_ONLY_SESSION_KEY in request.session:
        del request.session[IMPERSONATION_READ_ONLY_SESSION_KEY]
    request.session[IMPERSONATION_REASON_SESSION_KEY] = reason
    request.session.modified = True

    target_user = get_impersonated_user(request)
    posthoganalytics.capture(
        distinct_id=str(staff_user.distinct_id),
        event="impersonation_upgraded",
        properties={
            "staff_user_id": staff_user.id,
            "staff_user_email": staff_user.email,
            "target_user_id": target_user.id if target_user else None,
            "target_user_email": target_user.email if target_user else None,
            "reason": reason,
        },
    )
    _log_impersonation_mode_change(staff_user, target_user, reason, "read-write")

    return JsonResponse({"success": True})


@require_http_methods(["POST"])
def downgrade_impersonation(request):
    """Downgrade from read-write to read-only impersonation"""
    if not is_impersonated_session(request) or is_read_only_impersonation(request):
        raise Http404()

    try:
        data = json.loads(request.body)
        reason = data.get("reason", "").strip()
    except (json.JSONDecodeError, AttributeError):
        reason = ""

    if not reason:
        return JsonResponse({"error": "A reason is required to downgrade impersonation"}, status=400)

    staff_user = get_original_user_from_session(request)
    if not staff_user or not staff_user.is_staff:
        return JsonResponse({"error": "Unable to downgrade impersonation"}, status=400)

    request.session[IMPERSONATION_READ_ONLY_SESSION_KEY] = True
    request.session[IMPERSONATION_REASON_SESSION_KEY] = reason
    request.session.modified = True

    target_user = get_impersonated_user(request)
    posthoganalytics.capture(
        distinct_id=str(staff_user.distinct_id),
        event="impersonation_downgraded",
        properties={
            "staff_user_id": staff_user.id,
            "staff_user_email": staff_user.email,
            "target_user_id": target_user.id if target_user else None,
            "target_user_email": target_user.email if target_user else None,
            "reason": reason,
        },
    )
    _log_impersonation_mode_change(staff_user, target_user, reason, "read-only")

    return JsonResponse({"success": True})
