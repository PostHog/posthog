"""The provider incarnation base, and how the package finds every incarnation.

An incarnation is a thin module under `posthog/ingress/<provider>/`: header names, a
signature scheme, and how to read an event type and a delivery id off the request. It must
not import a product, and it must stay cheap to import, because the registry imports every
one of these on the first delivery.
"""

import json
import importlib
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any

from django.http import HttpRequest, HttpResponse

from rest_framework.throttling import BaseThrottle

from posthog import regions
from posthog.ingress.contracts import ProviderSpec, WebhookConsumer, WebhookDelivery
from posthog.ingress.verify.schemes import SignatureScheme, Verification, VerificationOutcome

# Every incarnation module, imported lazily. An incarnation exposes `SPECS` (what it accepts)
# and may expose `CORE_CONSUMERS` (consumers core owns rather than a product).
_INCARNATION_MODULES = (
    "posthog.ingress.github.provider",
    "posthog.ingress.slack.provider",
    "posthog.ingress.teams.provider",
    "posthog.ingress.pandadoc.provider",
    "posthog.ingress.mailgun.provider",
    "posthog.ingress.vapi.provider",
    "posthog.ingress.sns.provider",
    "posthog.ingress.vercel.provider",
)


class InvalidPayload(Exception):
    """A body the provider refuses, raised from `parse` or from `deliveries`.

    `parse` raises it for a body it cannot decode. `deliveries` raises it for a body it decoded
    and will not accept, which is where a provider holds the body to what the signature proved:
    Teams refuses an activity whose `serviceUrl` the token did not sign. Either way the view
    answers 400 and no consumer runs.

    Carries the provider's own message, which the view logs and never answers with: what the
    provider tripped over is a hint to an unauthenticated caller about how PostHog reads a body.
    A message that quotes a value the caller sent, or one the token carried, writes that value
    into the log of an endpoint a stranger can drive, so name the field instead of either value.
    """


class UnknownApp(ValueError):
    """A builder was handed an app name no spec of that provider declares."""


def require_known_app(provider: str, app: str, specs: Sequence[ProviderSpec]) -> None:
    """Refuse an app name the provider's `SPECS` do not declare.

    A typo otherwise builds a working endpoint: consumers register against the declared names,
    so nothing matches and every delivery is receipted and dropped, or the app has no secret
    getter and every delivery answers `NOT_CONFIGURED`. Both fail at the first real delivery
    rather than at import, so the mistake is caught here instead.
    """
    known = sorted(spec.app for spec in specs if spec.provider == provider)
    if app not in known:
        raise UnknownApp(f"Unknown {provider} app {app!r}, expected one of {known}")


def decode_json(raw: str | bytes) -> Any:
    """Decode a body this package accepts, or raise `InvalidPayload` for one it cannot read.

    One decoder for every provider, so which failures mean 400 is decided once. A provider that
    reads a form decodes the field it holds the JSON in through here.
    """
    try:
        # RecursionError: deeply nested JSON must answer 400, not 500.
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as error:
        raise InvalidPayload(str(error)) from error


class WebhookProvider(ABC):
    """One provider app: how a delivery is verified, and how it is read.

    The status codes are attributes rather than view arguments because they are part of the
    provider's own protocol: PandaDoc answers 404 on a bad signature by design, and Vapi
    answers 401. Everything else is a 202 transport receipt.
    """

    provider: str = ""
    app: str = ""
    invalid_signature_status: int = 403
    unconfigured_status: int = 500
    success_status: int = 202
    # A DRF throttle the view runs in front of verification, for a public endpoint whose
    # verification is expensive: Teams signs with a JWT, so the first thing an unsigned request
    # costs is a signing-key lookup. `None` runs no throttle, which is right for an endpoint
    # whose verification is a local HMAC. It must be a fixed-rate throttle: `build_webhook_view`
    # refuses a `ScopedRateThrottle`, whose scope lives on a view this one does not have.
    throttle_class: type[BaseThrottle] | None = None
    # Answered instead of the receipt when ingress cannot vouch that the delivery was accepted:
    # the forward to the owning region failed, a consumer raised, or the budget skipped a
    # consumer. A provider that redelivers on a non-2xx then sends the delivery again (Slack
    # does, GitHub does not), and `None` keeps the receipt for one that does not. The decision is
    # the transport's own, taken on whether the work ran at all, never on what a consumer returned.
    retry_status: int | None = None
    # An incarnation that answers 404 to withhold the endpoint's existence sets this False, so the
    # body does not name the reason the status code was chosen to hide.
    explains_rejections: bool = True
    # Whether a missing secret also reaches error tracking, on top of the log line every provider
    # writes. Off by default: an endpoint that answers an unconfigured request like an unknown
    # route (SNS) would let an unauthenticated prober fill error tracking from the outside. Turn it
    # on for an endpoint whose deliveries are lost while the secret is unset and where nothing else
    # would notice.
    reports_unconfigured: bool = False
    # How long the forward to the owning region may take. The default suits a small JSON body; a
    # provider whose deliveries carry uploaded files needs longer, because the forward rebuilds
    # and re-sends every part.
    forward_timeout_seconds: float = 3.0

    @abstractmethod
    def scheme(self) -> SignatureScheme:
        """The signature scheme for this app's secret."""

    @abstractmethod
    def deliveries(self, request: HttpRequest, payload: Any, facts: Mapping[str, Any]) -> Sequence[WebhookDelivery]:
        """Read zero or more deliveries out of one verified, parsed request.

        `facts` is what the signature scheme proved on the way, such as a signed token's
        verified claims. It is empty for a scheme that only checks an HMAC.

        Raise `InvalidPayload` for a body this provider will not accept, and the view answers
        400 before any consumer runs. That is how a provider holds a body field to the claim
        that signs it, rather than handing a consumer a delivery it has to distrust.
        """

    def receiving_region_domain(self) -> str:
        """The region whose URL this App is registered against.

        That region receives every delivery, and forwards the ones another region owns. Almost
        every third party holds the primary region's URL, which is why this is not a field: a
        provider that needs the other one overrides the method, and nothing else has to know.
        """
        return regions.PRIMARY_REGION_DOMAIN

    def verify(self, request: HttpRequest) -> Verification:
        scheme = self.scheme()
        # Asked before `request.body`, so an unsigned probe cannot make every endpoint here
        # read a body of up to the request limit before the signature header is even looked at.
        if scheme.rejects_headers(request.headers):
            return Verification(outcome=VerificationOutcome.INVALID)
        return scheme.verify(body=request.body, headers=request.headers)

    def parse(self, request: HttpRequest) -> Any:
        """Decode the verified body into the value `deliveries` reads.

        JSON is the default because every provider here posts JSON. A provider that posts a
        form instead (Slack interactivity, Mailgun) overrides this and reads `request.POST`.
        Raise `InvalidPayload` for a body this provider cannot read, and the view answers 400.
        """
        return decode_json(request.body)

    def pre_dispatch_response(self, request: HttpRequest, payload: Any) -> HttpResponse | None:
        """A handshake the protocol demands, answered before any consumer runs.

        Only that: Slack's `url_verification` challenge is the case. Never a side effect, and
        never anything a consumer's outcome decides. Regional forwarding used to live here and
        does not any more -- a consumer declares `ownership` and the view forwards.
        Returning `None` lets dispatch continue.
        """
        return None


def provider_specs() -> tuple[ProviderSpec, ...]:
    specs: list[ProviderSpec] = []
    for module_name in _INCARNATION_MODULES:
        module = importlib.import_module(module_name)
        specs.extend(getattr(module, "SPECS", ()))
    return tuple(specs)


def core_consumers() -> tuple[WebhookConsumer, ...]:
    consumers: list[WebhookConsumer] = []
    for module_name in _INCARNATION_MODULES:
        module = importlib.import_module(module_name)
        consumers.extend(getattr(module, "CORE_CONSUMERS", ()))
    return tuple(consumers)
