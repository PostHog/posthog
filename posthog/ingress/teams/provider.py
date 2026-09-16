"""Microsoft Teams Bot Framework activities.

Bot Framework authenticates every activity with a signed bearer token rather than a shared
secret, so this incarnation carries no secret at all: the signing-key URI, the audience and the
issuer allowlist arrive as getters from the product that owns the bot registration.

The verified claims become the delivery context, because the activity body carries the same
facts in plain JSON. A consumer that acts on the tenant or on `serviceUrl` must hold the body
to what the issuer actually signed.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from django.http import HttpRequest
from django.utils import timezone

from posthog.ingress.contracts import ProviderSpec, WebhookDelivery
from posthog.ingress.providers import WebhookProvider
from posthog.ingress.verify.jwt import BearerJwt
from posthog.ingress.verify.schemes import SignatureScheme
from posthog.rate_limit import TeamsEventWebhookThrottle

# The activity types a consumer may register for. Bot Framework has no subscription model, so
# it sends every activity type the channel produces; one this app does not act on finds no
# consumer and is answered with the receipt.
TEAMS_ACTIVITY_TYPES = frozenset({"message", "conversationUpdate"})

SPECS = (ProviderSpec(provider="teams", app="supporthog", event_types=TEAMS_ACTIVITY_TYPES),)

# The three RSA algorithms the Bot Framework OpenID metadata document publishes.
_SIGNING_ALGORITHMS = ("RS256", "RS384", "RS512")


class TeamsProvider(WebhookProvider):
    provider = "teams"
    # The endpoint is public and its verification ends in a signing-key lookup, so an unsigned
    # request is expensive. The cap has to be reached before verification, which is where the
    # view runs it.
    throttle_class = TeamsEventWebhookThrottle
    # Bot Framework retries an activity for about ten minutes on a 5xx or a timeout, with the
    # same activity id. A forward that never landed, or a handoff that raised, must therefore
    # answer a 5xx rather than the receipt, or the activity is lost.
    retry_status = 503

    def __init__(
        self,
        *,
        app: str = "supporthog",
        jwks_uri_getter: Callable[[], str | None],
        audience_getter: Callable[[], str | None],
        issuers_getter: Callable[[], frozenset[str]],
    ) -> None:
        self.app = app
        self._scheme = BearerJwt(
            jwks_uri_getter=jwks_uri_getter,
            audience_getter=audience_getter,
            issuers_getter=issuers_getter,
            algorithms=_SIGNING_ALGORITHMS,
        )

    def scheme(self) -> SignatureScheme:
        return self._scheme

    def deliveries(self, request: HttpRequest, payload: Any, facts: Mapping[str, Any]) -> Sequence[WebhookDelivery]:
        if not isinstance(payload, Mapping):
            return ()
        activity_id = payload.get("id")
        # The two claims a consumer holds the body to. The token itself never leaves the scheme:
        # the context is handed to a consumer and travels into its logs and its receipts.
        context = {
            "claim_tenant_id": str(facts.get("tid") or ""),
            "claim_service_url": str(facts.get("serviceurl") or ""),
        }
        return (
            WebhookDelivery(
                provider=self.provider,
                app=self.app,
                delivery_id=str(activity_id) if isinstance(activity_id, str) and activity_id else None,
                event_type=str(payload.get("type", "")),
                payload=payload,
                received_at=timezone.now(),
                context=context,
            ),
        )


def build_teams_provider(
    *,
    jwks_uri_getter: Callable[[], str | None],
    audience_getter: Callable[[], str | None],
    issuers_getter: Callable[[], frozenset[str]],
    app: str = "supporthog",
) -> TeamsProvider:
    """The bot registration belongs to the product, so its three verification values are passed in.

    `jwks_uri_getter` is called on every delivery. Bot Framework publishes its `jwks_uri` inside
    an OpenID metadata document, so that getter owns the discovery, the cache for it, and the
    allowlist check on a URI that came out of a remote document.
    """
    return TeamsProvider(
        app=app,
        jwks_uri_getter=jwks_uri_getter,
        audience_getter=audience_getter,
        issuers_getter=issuers_getter,
    )
