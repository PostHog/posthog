import json

from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.views.decorators.http import require_http_methods

import posthoganalytics
from loginas import settings as la_settings
from loginas.utils import is_impersonated_session
from loginas.views import user_login as loginas_user_login

from posthog.helpers.impersonation import get_original_user_from_session
from posthog.middleware import (
    IMPERSONATION_READ_ONLY_SESSION_KEY,
    IMPERSONATION_REASON_SESSION_KEY,
    is_read_only_impersonation,
)
from posthog.models import User


def loginas_user(request, user_id):
    staff_user = request.user
    response = loginas_user_login(request, user_id)

    # loginas redirects to LOGIN_REDIRECT only when the impersonation actually started; a rejected
    # attempt (empty reason, failed CAN_LOGIN_AS) redirects back to the referer without touching the
    # session. Gate the mutations on success so a rejected re-impersonation can't change the active
    # session's mode or reason.
    login_succeeded = (
        isinstance(response, HttpResponseRedirect)
        and response.url == la_settings.LOGIN_REDIRECT
        and is_impersonated_session(request)
    )

    if login_succeeded:
        is_read_only = request.POST.get("read_only") != "false"
        if is_read_only:
            request.session[IMPERSONATION_READ_ONLY_SESSION_KEY] = True
        elif IMPERSONATION_READ_ONLY_SESSION_KEY in request.session:
            # Re-impersonating the same user keeps the existing session (Django only flushes on a
            # user change), so clear a prior read-only flag to honor the mode requested here.
            del request.session[IMPERSONATION_READ_ONLY_SESSION_KEY]

        # Persist the reason server-side so it survives both Django-admin and in-app starts,
        # and can be surfaced to the frontend (autofill).
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
    request.session.modified = True

    posthoganalytics.capture(
        distinct_id=str(staff_user.distinct_id),
        event="impersonation_upgraded",
        properties={
            "staff_user_id": staff_user.id,
            "staff_user_email": staff_user.email,
            "target_user_id": request.user.id,
            "target_user_email": request.user.email,
            "reason": reason,
        },
    )

    return JsonResponse({"success": True})
