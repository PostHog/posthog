"""Email webhook endpoints for Mailgun routes, plus the cross-region sender lookup they need.

Three routes on one Mailgun account: the inbox address a customer writes to, the address a
customer's own agent blind-copies, and the catch-all that serves both. Each is an ingress app,
so verification, the receipt and the forward to the owning region all happen there, and the work
runs in `products/conversations/backend/services/mailgun_events.py`.
"""

from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from posthog.ingress.mailgun.provider import MailgunProvider, build_mailgun_provider
from posthog.ingress.verify.schemes import VerificationOutcome
from posthog.ingress.views import build_webhook_view

from products.conversations.backend.mailgun import get_email_webhook_signing_key

OUTBOUND_SENDER_LOOKUP_QUERY_PARAM = "sender_lookup"


class _OutboundMailgunProvider(MailgunProvider):
    """The outbound capture app, and the sender probe the other region ran before ingress.

    The regions do not deploy at the same instant, so for one release this route still has to
    recognise a `sender_lookup=1` probe from a region on the previous version. The probe carries a
    whole delivery, so dispatching it would ingest the probe as real mail. Answering it as a
    handshake keeps the shared view's verification, throttle and metrics. Delete this class, and
    the query parameter with it, once both regions run the ingress version.
    """

    def pre_dispatch_response(self, request: HttpRequest, payload: Any) -> HttpResponse | None:
        if request.GET.get(OUTBOUND_SENDER_LOOKUP_QUERY_PARAM) != "1":
            return None

        deliveries = self.deliveries(request, payload, {})
        if not deliveries:
            return HttpResponse(status=400)

        # Deferred because this module is on the URL conf's import path, and the ingestion modules
        # behind the facade are not cheap to import.
        from products.conversations.backend.facade.api import mailgun_legacy_sender_lookup_status  # noqa: PLC0415

        return HttpResponse(status=mailgun_legacy_sender_lookup_status(deliveries[0]))


_outbound_provider = _OutboundMailgunProvider("outbound", signing_key_getter=get_email_webhook_signing_key)

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
        SENDER_STATUS_ABSENT_BODY,
        SENDER_STATUS_ACTIVE,
    )

    if mailgun_sender_is_active_here(request.POST.get("sender", "")):
        return HttpResponse(status=SENDER_STATUS_ACTIVE)
    # The body is what tells this answer apart from the 404 a region without this route answers.
    return JsonResponse(SENDER_STATUS_ABSENT_BODY, status=SENDER_STATUS_ABSENT)
