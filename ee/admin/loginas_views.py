import json
import uuid

from django.http import Http404, JsonResponse
from django.views.decorators.http import require_http_methods

import posthoganalytics
from loginas.utils import is_impersonated_session
from loginas.views import user_login as loginas_user_login

from posthog.helpers.impersonation import get_original_user_from_session
from posthog.middleware import (
    IMPERSONATION_READ_ONLY_SESSION_KEY,
    IMPERSONATION_TICKET_ID_SESSION_KEY,
    is_read_only_impersonation,
)
from posthog.models import User


def _configure_impersonation_session(
    request,
    staff_user,
    target_user,
    *,
    is_read_only: bool = True,
    reason: str = "",
    ticket_id: str | None = None,
):
    """Set session flags and capture analytics after a successful impersonation login."""
    if not is_impersonated_session(request):
        return

    if is_read_only:
        request.session[IMPERSONATION_READ_ONLY_SESSION_KEY] = True

    if ticket_id:
        request.session[IMPERSONATION_TICKET_ID_SESSION_KEY] = ticket_id

    properties = {
        "mode": "read_only" if is_read_only else "read_write",
        "reason": reason,
        "staff_user_id": staff_user.id,
        "staff_user_email": staff_user.email,
        "target_user_id": target_user.id if target_user else None,
        "target_user_email": target_user.email if target_user else None,
    }
    if ticket_id:
        properties["ticket_id"] = ticket_id

    posthoganalytics.capture(
        distinct_id=str(staff_user.distinct_id),
        event="impersonation_started",
        properties=properties,
    )


def loginas_user(request, user_id):
    staff_user = request.user
    response = loginas_user_login(request, user_id)

    target_user = User.objects.filter(id=user_id).first()
    _configure_impersonation_session(
        request,
        staff_user,
        target_user,
        is_read_only=request.POST.get("read_only") != "false",
        reason=request.POST.get("reason", ""),
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


@require_http_methods(["POST"])
def loginas_user_from_ticket(request):
    """Initiate impersonation from a support ticket, resolving the ticket's customer email to a User.

    Staff/permission checks are handled by CAN_LOGIN_AS in django-loginas
    (see posthog/settings/web.py) when loginas_user_login is called.
    """
    if not request.user.is_staff:
        raise Http404()

    try:
        data = json.loads(request.body)
        ticket_id = data.get("ticket_id", "").strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid request body"}, status=400)

    if not ticket_id:
        return JsonResponse({"error": "ticket_id is required"}, status=400)

    try:
        uuid.UUID(ticket_id)
    except ValueError:
        return JsonResponse({"error": "ticket_id must be a valid UUID"}, status=400)

    from products.conversations.backend.models import Ticket

    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        raise Http404("Ticket not found")

    email = ticket.anonymous_traits.get("email") if ticket.anonymous_traits else None
    if not email:
        return JsonResponse({"error": "Ticket has no associated email"}, status=400)

    target_user = User.objects.filter(email__iexact=email).first()
    if not target_user:
        return JsonResponse({"error": "No user found for this email"}, status=404)

    reason = f"Support ticket #{ticket.ticket_number}"

    # django-loginas reads reason from request.POST, so inject it for the reason check
    request.POST = request.POST.copy()
    request.POST["reason"] = reason

    staff_user = request.user
    loginas_user_login(request, str(target_user.id))

    _configure_impersonation_session(
        request,
        staff_user,
        target_user,
        is_read_only=True,
        reason=reason,
        ticket_id=str(ticket.id),
    )

    if is_impersonated_session(request):
        return JsonResponse({"success": True, "ticket_id": str(ticket.id)})

    return JsonResponse({"error": "Failed to initiate impersonation"}, status=403)


@require_http_methods(["GET"])
def get_impersonation_ticket(request):
    """Get the support ticket associated with the current impersonation session."""
    if not is_impersonated_session(request):
        raise Http404()

    ticket_id = request.session.get(IMPERSONATION_TICKET_ID_SESSION_KEY)
    if not ticket_id:
        raise Http404()

    try:
        uuid.UUID(ticket_id)
    except (ValueError, AttributeError):
        raise Http404()

    from products.conversations.backend.models import Ticket

    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        raise Http404()

    return JsonResponse(
        {
            "id": str(ticket.id),
            "ticket_number": ticket.ticket_number,
            "team_id": ticket.team_id,
        }
    )
