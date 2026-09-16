"""The one inbound webhook view: verify, parse, dispatch, answer a fixed receipt."""

import json
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.ingress.dispatch.budget import DeliveryBudget, delivery_budget_seconds
from posthog.ingress.dispatch.loading import get_dispatcher
from posthog.ingress.observability.metrics import observe_delivery
from posthog.ingress.providers import WebhookProvider
from posthog.ingress.verify.schemes import VerificationOutcome

logger = structlog.get_logger(__name__)


def build_webhook_view(provider: WebhookProvider) -> Callable[[HttpRequest], HttpResponse]:
    """A Django view for one provider app.

    The response is a transport receipt. Verification, method and payload decide the status;
    consumers never do, and their return values are ignored.
    """

    @csrf_exempt
    def webhook_view(request: HttpRequest) -> HttpResponse:
        if request.method != "POST":
            observe_delivery(provider=provider.provider, app=provider.app, outcome="method_not_allowed")
            return HttpResponse(status=405)

        outcome = provider.verify(request)
        if outcome is VerificationOutcome.NOT_CONFIGURED:
            logger.error("ingress_webhook_not_configured", provider=provider.provider, app=provider.app)
            observe_delivery(provider=provider.provider, app=provider.app, outcome="not_configured")
            reason = "Webhook not configured" if provider.explains_rejections else ""
            return HttpResponse(reason, status=provider.unconfigured_status)
        if outcome is not VerificationOutcome.VERIFIED:
            observe_delivery(provider=provider.provider, app=provider.app, outcome="invalid_signature")
            reason = "Invalid signature" if provider.explains_rejections else ""
            return HttpResponse(reason, status=provider.invalid_signature_status)

        try:
            # RecursionError: deeply nested JSON must answer 400, not 500.
            payload = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
            logger.warning(
                "ingress_delivery_invalid_payload", provider=provider.provider, app=provider.app, error=str(exc)
            )
            observe_delivery(provider=provider.provider, app=provider.app, outcome="invalid_payload")
            return HttpResponse("Invalid JSON", status=400)

        handshake = provider.pre_dispatch_response(request, payload)
        if handshake is not None:
            observe_delivery(provider=provider.provider, app=provider.app, outcome="accepted")
            return handshake

        dispatcher = get_dispatcher()
        # One budget for the whole request, not one per delivery: PandaDoc turns a batched body
        # into many deliveries, and a budget each would hold the request open for the sum.
        budget = DeliveryBudget(delivery_budget_seconds())
        for delivery in provider.deliveries(request, payload):
            dispatcher.dispatch(delivery, budget=budget)

        observe_delivery(provider=provider.provider, app=provider.app, outcome="accepted")
        return HttpResponse(status=provider.success_status)

    webhook_view.__name__ = f"{provider.provider}_{provider.app}_webhook"
    return webhook_view
