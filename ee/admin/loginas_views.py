import json
import uuid
from typing import TYPE_CHECKING, cast
from urllib.parse import urlencode

from django.apps import apps
from django.conf import settings
from django.db.models import Q
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
    IMPERSONATION_TICKET_ID_SESSION_KEY,
    is_read_only_impersonation,
)
from posthog.models import User

if TYPE_CHECKING:
    from products.conversations.backend.models import Ticket

REGION_DOMAINS: dict[str, str] = {
    "US": "us.posthog.com",
    "EU": "eu.posthog.com",
}


def _get_ticket(ticket_id: str, user: User) -> "Ticket | None":
    """Fetch a support ticket by ID, restricted to PostHog's internal support team.

    In local dev (DEBUG — asserted off in production) the lookup falls back to the
    staff user's current project, so the flow is testable without recreating the
    internal project id or setting POSTHOG_INTERNAL_TEAM_ID.
    """
    ticket_model = apps.get_model("conversations", "Ticket")
    team_id = settings.POSTHOG_INTERNAL_TEAM_ID
    if settings.DEBUG and user.current_team_id:
        team_id = user.current_team_id
    try:
        return cast("Ticket", ticket_model.objects.get(id=ticket_id, team_id=team_id))
    except ticket_model.DoesNotExist:
        return None


def _configure_impersonation_session(
    request,
    staff_user,
    target_user,
    *,
    is_read_only: bool = True,
    reason: str = "",
    ticket_id: str | None = None,
) -> None:
    """Set session flags and capture analytics after a successful impersonation login."""
    if not is_impersonated_session(request):
        return

    if is_read_only:
        request.session[IMPERSONATION_READ_ONLY_SESSION_KEY] = True
    elif IMPERSONATION_READ_ONLY_SESSION_KEY in request.session:
        # Re-impersonating the same user keeps the existing session (Django only flushes on a
        # user change), so clear a prior read-only flag to honor the mode requested here.
        del request.session[IMPERSONATION_READ_ONLY_SESSION_KEY]

    # Persist the reason server-side so it survives both Django-admin and in-app starts,
    # and can be surfaced to the frontend (autofill).
    request.session[IMPERSONATION_REASON_SESSION_KEY] = reason

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
    """Initiate read-only impersonation from a support ticket, resolving the ticket's customer email to a User.

    Staff/permission checks are also enforced by CAN_LOGIN_AS in django-loginas
    (see posthog/settings/web.py) when loginas_user_login is called.
    """
    if not request.user.is_staff:
        return JsonResponse({"error": "Not found"}, status=404)

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

    ticket = _get_ticket(ticket_id, request.user)
    if not ticket:
        if settings.DEBUG:
            error = "Ticket not found in your current project (in local dev, tickets are looked up in the project you're currently in)."
        else:
            error = (
                f"Ticket not found. Ticket impersonation is only possible for tickets in "
                f"project {settings.POSTHOG_INTERNAL_TEAM_ID} (PostHog's internal support project, US region)."
            )
        return JsonResponse({"error": error}, status=404)

    # Block when the claimed identity was assessed but not attested (False). A null
    # value means the signal was never assessed (e.g. pre-dates it), which the UI
    # surfaces as a caution rather than a hard block, so only reject an explicit False.
    if ticket.identity_verified is False:
        return JsonResponse(
            {
                "error": "This ticket's identity could not be verified, so logging in as the customer is disabled. Verify the customer's identity and login from admin manually."
            },
            status=400,
        )

    # When the ticket originated in another region, point staff at that region's
    # admin rather than trying (and failing) to resolve the user locally. The region
    # trait is customer-suppliable, so unknown values fall through to a local lookup.
    ticket_region = ((ticket.anonymous_traits or {}).get("region") or "").upper()
    current_region = (settings.CLOUD_DEPLOYMENT or "").upper()
    if ticket_region in REGION_DOMAINS and current_region in REGION_DOMAINS and ticket_region != current_region:
        email = (ticket.anonymous_traits or {}).get("email", "")
        redirect_url = f"https://{REGION_DOMAINS[ticket_region]}/admin/posthog/user/"
        if email:
            redirect_url += f"?{urlencode({'q': email})}"
        return JsonResponse({"redirect_region": ticket_region, "redirect_url": redirect_url})

    if ticket.identity_verified and ticket.channel_source == "widget":
        # On HMAC-verified widget tickets the attested identity is distinct_id; the email
        # trait stays customer-mutable on every widget message, so resolving by it would
        # let a verified ticket point login-as at an unrelated account. Match users
        # identified by distinct_id or by email — both compared against the attested value,
        # with no fallback to the mutable trait.
        target_user = User.objects.filter(
            Q(distinct_id=ticket.distinct_id) | Q(email__iexact=ticket.distinct_id)
        ).first()
        if not target_user:
            return JsonResponse({"error": "No user found for this ticket's verified identity"}, status=404)
    else:
        email = ticket.anonymous_traits.get("email") if ticket.anonymous_traits else None
        if not email:
            return JsonResponse({"error": "Ticket has no associated email"}, status=400)

        target_user = User.objects.filter(email__iexact=email).first()
        if not target_user:
            return JsonResponse({"error": "No user found for this email"}, status=404)

    reason = f"Support ticket #{ticket.ticket_number}"

    # django-loginas reads the reason from request.POST, so inject it for the reason check.
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
