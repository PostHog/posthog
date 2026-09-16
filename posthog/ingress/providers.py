"""The provider incarnation base, and how the package finds every incarnation.

An incarnation is a thin module under `posthog/ingress/<provider>/`: header names, a
signature scheme, and how to read an event type and a delivery id off the request. It must
not import a product, and it must stay cheap to import, because the registry imports every
one of these on the first delivery.
"""

import importlib
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from django.http import HttpRequest, HttpResponse

from posthog.ingress.contracts import ProviderSpec, WebhookConsumer, WebhookDelivery
from posthog.ingress.verify.schemes import SignatureScheme, VerificationOutcome

# Every incarnation module, imported lazily. An incarnation exposes `SPECS` (what it accepts)
# and may expose `CORE_CONSUMERS` (consumers core owns rather than a product).
_INCARNATION_MODULES = (
    "posthog.ingress.github.provider",
    "posthog.ingress.slack.provider",
    "posthog.ingress.pandadoc.provider",
    "posthog.ingress.vapi.provider",
    "posthog.ingress.sns.provider",
)


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
    # An incarnation that answers 404 to withhold the endpoint's existence sets this False, so the
    # body does not name the reason the status code was chosen to hide.
    explains_rejections: bool = True

    @abstractmethod
    def scheme(self) -> SignatureScheme:
        """The signature scheme for this app's secret."""

    @abstractmethod
    def deliveries(self, request: HttpRequest, payload: Any) -> Sequence[WebhookDelivery]:
        """Read zero or more deliveries out of one verified, parsed request."""

    def verify(self, request: HttpRequest) -> VerificationOutcome:
        return self.scheme().verify(body=request.body, headers=request.headers)

    def pre_dispatch_response(self, request: HttpRequest, payload: Any) -> HttpResponse | None:
        """A response the provider's protocol demands before any consumer runs.

        Only handshakes belong here (Slack's `url_verification` challenge), never anything a
        consumer's outcome decides.
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
