"""The one inbound webhook view: throttle, verify, parse, dispatch, answer a fixed receipt."""

import math
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog
from rest_framework.request import Request as DRFRequest
from rest_framework.throttling import ScopedRateThrottle

from posthog.exceptions_capture import capture_exception
from posthog.ingress.dispatch.budget import DeliveryBudget, delivery_budget_seconds
from posthog.ingress.dispatch.forward import forward_to_other_region
from posthog.ingress.dispatch.loading import get_dispatcher
from posthog.ingress.observability.metrics import observe_delivery
from posthog.ingress.providers import InvalidPayload, WebhookProvider
from posthog.ingress.verify.schemes import VerificationOutcome
from posthog.regions import other_region_domain

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


def _retry_refusal(provider: WebhookProvider, consumers: list[str]) -> HttpResponse:
    """The status a provider that redelivers needs, for a delivery ingress cannot vouch for."""
    # The dispatcher already logged and captured the failure itself, so this only says the request
    # is not being receipted, and which consumers cost it that.
    logger.warning(
        "ingress_delivery_retry_requested",
        provider=provider.provider,
        app=provider.app,
        consumers=consumers,
    )
    observe_delivery(provider=provider.provider, app=provider.app, outcome="retry_requested")
    return HttpResponse("Delivery not accepted", status=provider.retry_status)


def build_webhook_view(provider: WebhookProvider) -> Callable[[HttpRequest], HttpResponse]:
    """A Django view for one provider app.

    The response is a transport receipt: the method, the throttle, verification and the payload
    decide the status, and a consumer's return value is ignored. A provider that sets
    `retry_status` also gets that status when the work did not run at all, which is the
    transport saying so rather than a consumer choosing an answer.
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
            # An incarnation that answers a 4xx may stay off until an operator configures it, and its
            # URL is public meanwhile, so what reaches this line is probe traffic. A warning still
            # reaches an operator, and at error level an anonymous prober would decide how much of
            # the error budget this endpoint spends.
            log = logger.warning if provider.unconfigured_status < 500 else logger.error
            log("ingress_webhook_not_configured", provider=provider.provider, app=provider.app)
            if provider.reports_unconfigured:
                capture_exception(
                    Exception(f"Inbound webhook {provider.provider}/{provider.app} has no secret configured")
                )
            observe_delivery(provider=provider.provider, app=provider.app, outcome="not_configured")
            reason = "Webhook not configured" if provider.explains_rejections else ""
            return HttpResponse(reason, status=provider.unconfigured_status)
        if verification.outcome is VerificationOutcome.UNAVAILABLE:
            # The check never ran, so nothing here is the caller's fault. 503 asks any sender that
            # retries a server error to send the delivery again, which the invalid-signature status
            # would not: that one reads as a verdict on the signature.
            logger.warning("ingress_verify_unavailable", provider=provider.provider, app=provider.app)
            observe_delivery(provider=provider.provider, app=provider.app, outcome="verify_unavailable")
            return HttpResponse("Verification unavailable", status=503)
        if verification.outcome is not VerificationOutcome.VERIFIED:
            observe_delivery(provider=provider.provider, app=provider.app, outcome="invalid_signature")
            reason = "Invalid signature" if provider.explains_rejections else ""
            return HttpResponse(reason, status=provider.invalid_signature_status)

        def refuse_payload(error: InvalidPayload) -> HttpResponse:
            observe_delivery(provider=provider.provider, app=provider.app, outcome="invalid_payload")
            logger.warning(
                "ingress_delivery_invalid_payload",
                provider=provider.provider,
                app=provider.app,
                error=str(error),
            )
            return HttpResponse("Invalid JSON", status=400)

        # Parse after verification, and keep that order: a provider that reads a form body
        # overrides `parse` and reads `request.POST`, and under ASGI that read consumes the
        # stream, so `request.body` is no longer available to the signature check afterwards.
        try:
            payload = provider.parse(request)
        except InvalidPayload as error:
            return refuse_payload(error)

        handshake = provider.pre_dispatch_response(request, payload)
        if handshake is not None:
            observe_delivery(provider=provider.provider, app=provider.app, outcome="accepted")
            return handshake

        dispatcher = get_dispatcher()
        # `deliveries` refuses a body the same way `parse` does, because a provider can only
        # hold the body to the verified claims once it has both. Teams does: an activity whose
        # `serviceUrl` the token did not sign never becomes a delivery.
        try:
            deliveries = provider.deliveries(request, payload, verification.facts)
        except InvalidPayload as error:
            return refuse_payload(error)
        # One budget for the whole request, not one per delivery: PandaDoc turns a batched body
        # into many deliveries, and a budget each would hold the request open for the sum. It
        # starts before the ownership lookups, which read the database and forward on the same
        # request path.
        budget = DeliveryBudget(delivery_budget_seconds())

        elsewhere: dict[str, None] = {}
        unanswered: dict[str, None] = {}
        for delivery in deliveries:
            answers = dispatcher.ownership_of(delivery)
            elsewhere.update(dict.fromkeys(answers.elsewhere_consumers))
            unanswered.update(dict.fromkeys(answers.failed_consumers))

        if unanswered and provider.retry_status is not None:
            # A lookup that did not answer rules no region out, so this region cannot tell whether
            # the other one owns the delivery. Dispatching locally would run every consumer, find
            # nothing to do, and receipt a delivery the owning region never sees. Asking for the
            # delivery again runs the lookups again, and it happens here, before the forward and
            # before any consumer claims a dedup mark that would swallow the redelivery.
            return _retry_refusal(provider, list(unanswered))

        if elsewhere:
            if request.get_host() == provider.receiving_region_domain():
                # Once for the request, not once per delivery: what is replayed is the signed body.
                forwarded = forward_to_other_region(
                    request,
                    target_domain=other_region_domain(provider.receiving_region_domain()),
                    provider=provider.provider,
                    app=provider.app,
                    timeout=provider.forward_timeout_seconds,
                )
                if not forwarded and provider.retry_status is not None:
                    observe_delivery(provider=provider.provider, app=provider.app, outcome="forward_failed")
                    return HttpResponse(status=provider.retry_status)
            elif request.get_host() == other_region_domain(provider.receiving_region_domain()):
                # This region is the one deliveries are forwarded to, so a local miss here is that
                # consumer's unresolved routing, not proof that no region owns the delivery.
                logger.warning(
                    "ingress_delivery_unowned_here",
                    provider=provider.provider,
                    app=provider.app,
                    consumers=list(elsewhere),
                )
            else:
                # Neither region answers on this host, so the forward is skipped and the delivery is
                # receipted here whatever the consumer said. The likely cause is a callback URL
                # registered against a hostname no region names, and nothing else reports it.
                logger.warning(
                    "ingress_delivery_host_matches_no_region",
                    provider=provider.provider,
                    app=provider.app,
                    host=request.get_host(),
                    consumers=list(elsewhere),
                )

        unaccepted: dict[str, None] = {}
        for delivery in deliveries:
            dispatched = dispatcher.dispatch(delivery, budget=budget)
            unaccepted.update(dict.fromkeys(dispatched.unaccepted_consumers))

        if unaccepted and provider.retry_status is not None:
            return _retry_refusal(provider, list(unaccepted))

        observe_delivery(provider=provider.provider, app=provider.app, outcome="accepted")
        return HttpResponse(status=provider.success_status)

    webhook_view.__name__ = f"{provider.provider}_{provider.app}_webhook"
    return webhook_view
