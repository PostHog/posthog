import json
import dataclasses
from typing import Optional

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
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, log_activity

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class ImpersonationContext(ActivityContextBase):
    staff_user_email: str
    target_user_email: Optional[str]
    reason: str
    mode: str


def _log_impersonation_mode_change(staff_user: User, target_user: Optional[User], reason: str, activity: str) -> None:
    """Record an impersonation upgrade/downgrade in the activity log (staff-only visibility).

    Actor is the original staff user; the entry is scoped to the impersonated user's org so it
    surfaces in the org-level activity log. Logging must never break the mode change itself.
    """
    if not target_user or not target_user.current_organization_id:
        return
    mode = "read_write" if activity == "impersonation_upgraded" else "read_only"
    try:
        log_activity(
            organization_id=target_user.current_organization_id,
            team_id=None,
            user=staff_user,
            item_id=target_user.id,
            scope="User",
            activity=activity,
            detail=Detail(
                name=target_user.email,
                changes=[],
                context=ImpersonationContext(
                    staff_user_email=staff_user.email,
                    target_user_email=target_user.email,
                    reason=reason,
                    mode=mode,
                ),
            ),
            was_impersonated=True,
        )
    except Exception:
        logger.exception("Failed to log impersonation mode change", activity=activity)


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
    _log_impersonation_mode_change(staff_user, target_user, reason, "impersonation_upgraded")

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
    _log_impersonation_mode_change(staff_user, target_user, reason, "impersonation_downgraded")

    return JsonResponse({"success": True})
