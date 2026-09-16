"""The one inbound webhook view: throttle, verify, parse, dispatch, answer a fixed receipt."""

import math
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog
from rest_framework.request import Request as DRFRequest
from rest_framework.throttling import ScopedRateThrottle

from posthog.ingress.contracts import DeliveryOwnership
from posthog.ingress.dispatch.budget import DeliveryBudget, delivery_budget_seconds
from posthog.ingress.dispatch.forward import forward_to_secondary_region
from posthog.ingress.dispatch.loading import get_dispatcher
from posthog.ingress.observability.metrics import observe_delivery
from posthog.ingress.providers import InvalidPayload, WebhookProvider
from posthog.ingress.verify.schemes import VerificationOutcome
from posthog.regions import is_primary_region

logger = structlog.get_logger(__name__)


def _throttle_refusal(provider: WebhookProvider, request: HttpRequest) -> HttpResponse | None:
    """The 429 this provider's throttle asks for, or `None` when the request may continue."""
    throttle_class = provider.throttle_class
    if throttle_class is None:
        return None

    throttle = throttle_class()
    # DRF throttles read a DRF request and this is a plain Django view, so the request is
    # wrapped rather than the throttle reimplemented: the rates live in `posthog.rate_limit`
    # with every other throttle, and a wrapped request carries the headers they key on.
    if throttle.allow_request(DRFRequest(request), view=None):  # type: ignore[arg-type]
        return None

    observe_delivery(provider=provider.provider, app=provider.app, outcome="throttled")
    response = HttpResponse(status=429)
    wait = throttle.wait()
    if wait is not None:
        # Rounded up, so a caller that obeys the header comes back after the window rather
        # than inside it and spends its next attempt on another 429.
        response["Retry-After"] = str(math.ceil(wait))
    return response


def build_webhook_view(provider: WebhookProvider) -> Callable[[HttpRequest], HttpResponse]:
    """A Django view for one provider app.

    The response is a transport receipt. The method, the throttle, verification and the payload
    decide the status; consumers never do, and their return values are ignored.
    """
    # Refused at build rather than per request, because the failure is silent at request time:
    # a ScopedRateThrottle reads its rate from the view's `throttle_scope`, finds none here, and
    # permits every request. An endpoint that looks capped and is not is worse than no cap.
    if provider.throttle_class is not None and issubclass(provider.throttle_class, ScopedRateThrottle):
        raise TypeError(
            f"Provider {provider.provider}/{provider.app} sets a ScopedRateThrottle. "
            "A scoped throttle reads its scope off a view, and this webhook view has none, "
            "so it would permit every request. Use a fixed-rate throttle from posthog.rate_limit."
        )

    @csrf_exempt
    def webhook_view(request: HttpRequest) -> HttpResponse:
        if request.method != "POST":
            observe_delivery(provider=provider.provider, app=provider.app, outcome="method_not_allowed")
            return HttpResponse(status=405)

        # The throttle runs in front of verification, because on a provider that signs with a
        # JWT the verification is the expensive half: an unsigned request would otherwise buy
        # a signing-key lookup before anything caps how many of them arrive.
        throttled = _throttle_refusal(provider, request)
        if throttled is not None:
            return throttled

        verification = provider.verify(request)
        if verification.outcome is VerificationOutcome.NOT_CONFIGURED:
            logger.error("ingress_webhook_not_configured", provider=provider.provider, app=provider.app)
            observe_delivery(provider=provider.provider, app=provider.app, outcome="not_configured")
            reason = "Webhook not configured" if provider.explains_rejections else ""
            return HttpResponse(reason, status=provider.unconfigured_status)
        if verification.outcome is not VerificationOutcome.VERIFIED:
            observe_delivery(provider=provider.provider, app=provider.app, outcome="invalid_signature")
            reason = "Invalid signature" if provider.explains_rejections else ""
            return HttpResponse(reason, status=provider.invalid_signature_status)

        # Parse after verification, and keep that order: a provider that reads a form body
        # overrides `parse` and reads `request.POST`, and under ASGI that read consumes the
        # stream, so `request.body` is no longer available to the signature check afterwards.
        try:
            payload = provider.parse(request)
        except InvalidPayload as error:
            observe_delivery(provider=provider.provider, app=provider.app, outcome="invalid_payload")
            logger.warning(
                "ingress_delivery_invalid_payload",
                provider=provider.provider,
                app=provider.app,
                error=str(error),
            )
            return HttpResponse("Invalid JSON", status=400)

        handshake = provider.pre_dispatch_response(request, payload)
        if handshake is not None:
            observe_delivery(provider=provider.provider, app=provider.app, outcome="accepted")
            return handshake

        dispatcher = get_dispatcher()
        deliveries = provider.deliveries(request, payload, verification.facts)
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
