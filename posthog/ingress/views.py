"""The one inbound webhook view: verify, parse, dispatch, answer a fixed receipt."""

import json
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.ingress.contracts import DeliveryOwnership
from posthog.ingress.dispatch.budget import DeliveryBudget, delivery_budget_seconds
from posthog.ingress.dispatch.forward import forward_to_secondary_region
from posthog.ingress.dispatch.loading import get_dispatcher
from posthog.ingress.observability.metrics import observe_delivery
from posthog.ingress.providers import WebhookProvider
from posthog.ingress.verify.schemes import VerificationOutcome
from posthog.regions import is_primary_region

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
            return HttpResponse("Webhook not configured", status=provider.unconfigured_status)
        if outcome is not VerificationOutcome.VERIFIED:
            observe_delivery(provider=provider.provider, app=provider.app, outcome="invalid_signature")
            return HttpResponse("Invalid signature", status=provider.invalid_signature_status)

        try:
            # RecursionError: deeply nested JSON must answer 400, not 500.
            payload = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            observe_delivery(provider=provider.provider, app=provider.app, outcome="invalid_payload")
            return HttpResponse("Invalid JSON", status=400)

        handshake = provider.pre_dispatch_response(request, payload)
        if handshake is not None:
            observe_delivery(provider=provider.provider, app=provider.app, outcome="accepted")
            return handshake

        dispatcher = get_dispatcher()
        deliveries = provider.deliveries(request, payload)
        # One budget for the whole request, not one per delivery: PandaDoc turns a batched body
        # into many deliveries, and a budget each would hold the request open for the sum. It
        # starts before the ownership lookups, which read the database and forward on the same
        # request path.
        budget = DeliveryBudget(delivery_budget_seconds())

        elsewhere: dict[str, None] = {}
        for delivery in deliveries:
            ownership, consumers = dispatcher.ownership_of(delivery)
            if ownership is DeliveryOwnership.ELSEWHERE:
                elsewhere.update(dict.fromkeys(consumers))
        if elsewhere:
            if is_primary_region(request):
                # Once for the request, not once per delivery: what is replayed is the signed body.
                forwarded = forward_to_secondary_region(request, provider=provider.provider, app=provider.app)
                if not forwarded and provider.forward_failure_status is not None:
                    observe_delivery(provider=provider.provider, app=provider.app, outcome="forward_failed")
                    return HttpResponse(status=provider.forward_failure_status)
            else:
                # A local miss on the secondary region is that consumer's unresolved routing, not
                # proof that no region owns the delivery.
                logger.warning(
                    "ingress_delivery_unowned_here",
                    provider=provider.provider,
                    app=provider.app,
                    consumers=list(elsewhere),
                )

        for delivery in deliveries:
            dispatcher.dispatch(delivery, budget=budget)

        observe_delivery(provider=provider.provider, app=provider.app, outcome="accepted")
        return HttpResponse(status=provider.success_status)

    webhook_view.__name__ = f"{provider.provider}_{provider.app}_webhook"
    return webhook_view
