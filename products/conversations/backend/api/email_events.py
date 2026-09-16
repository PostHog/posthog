"""Email webhook endpoints for Mailgun routes, plus the cross-region sender lookup they need.

Three routes on one Mailgun account: the inbox address a customer writes to, the address a
customer's own agent blind-copies, and the catch-all that serves both. Each is an ingress app,
so verification, the receipt and the forward to the owning region all happen there, and the work
runs in `products/conversations/backend/services/mailgun_events.py`.
"""

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

from posthog.ingress.mailgun.provider import build_mailgun_provider
from posthog.ingress.verify.schemes import VerificationOutcome
from posthog.ingress.views import build_webhook_view

from products.conversations.backend.mailgun import get_email_webhook_signing_key

_outbound_provider = build_mailgun_provider("outbound", signing_key_getter=get_email_webhook_signing_key)

email_inbound_handler = build_webhook_view(
    build_mailgun_provider("inbound", signing_key_getter=get_email_webhook_signing_key)
)
email_outbound_handler = build_webhook_view(_outbound_provider)
email_capture_handler = build_webhook_view(
    build_mailgun_provider("capture", signing_key_getter=get_email_webhook_signing_key)
)


@csrf_exempt
def email_sender_status_handler(request: HttpRequest) -> HttpResponse:
    """Answer whether this region holds an active channel for a sender the other region captured.

    Channel uniqueness is per region, so a sender active in both would attach one team's private
    outbound mail to the other team's thread. The asking region replays the delivery's own Mailgun
    signature triple, so the verifier the outbound route already uses is what proves the caller is
    holding a real delivery. This is not a webhook path: nothing is ingested here.
    """
    if request.method != "POST":
        return HttpResponse(status=405)
    if _outbound_provider.verify(request).outcome is not VerificationOutcome.VERIFIED:
        return HttpResponse("Invalid signature", status=403)

    # Deferred because this module is on the URL conf's import path, and the ingestion modules
    # behind the facade are not cheap to import.
    from products.conversations.backend.facade.api import mailgun_sender_is_active_here  # noqa: PLC0415
    from products.conversations.backend.services.mailgun_events import (  # noqa: PLC0415
        SENDER_STATUS_ABSENT,
        SENDER_STATUS_ACTIVE,
    )

    if mailgun_sender_is_active_here(request.POST.get("sender", "")):
        return HttpResponse(status=SENDER_STATUS_ACTIVE)
    return HttpResponse(status=SENDER_STATUS_ABSENT)
