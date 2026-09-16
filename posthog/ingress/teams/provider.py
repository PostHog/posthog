"""Microsoft Teams Bot Framework activities.

Bot Framework authenticates every activity with a signed bearer token rather than a shared
secret, so this incarnation carries no secret at all: the signing-key URI, the audience and the
issuer allowlist arrive as getters from the product that owns the bot registration.

The activity body repeats in plain JSON what the token signs, and Bot Framework's connector
authentication says the two must agree. This incarnation enforces that before a consumer sees
the delivery, so a consumer can read `serviceUrl` off the body and act on it.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from django.http import HttpRequest
from django.utils import timezone

from posthog.ingress.contracts import ProviderSpec, WebhookDelivery
from posthog.ingress.providers import InvalidPayload, WebhookProvider
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


def _body_tenant_id(payload: Mapping[str, Any]) -> str:
    channel_data = payload.get("channelData")
    channel_data = channel_data if isinstance(channel_data, Mapping) else {}
    tenant = channel_data.get("tenant")
    tenant = tenant if isinstance(tenant, Mapping) else {}
    return str(tenant.get("id") or "")


def _matched_service_url(payload: Mapping[str, Any], facts: Mapping[str, Any]) -> str:
    """The activity's `serviceUrl`, once the token proves the issuer signed that same URL.

    Bot Framework's connector authentication requires the `serviceurl` claim to be present and
    to equal the activity's `serviceUrl`, and its own SDKs compare the two as strings without
    regard to case. The claim is what makes the body field safe to use: the bot sends its bearer
    token to that URL, so a caller holding any valid Bot Framework token could otherwise point
    the credential at a host of its choosing.

    Trailing slashes are stripped from both sides before the comparison, because Teams sends the
    URL with one in the body and without one in the claim.
    """
    claim_service_url = str(facts.get("serviceurl") or "").rstrip("/")
    if not claim_service_url:
        raise InvalidPayload("the token carries no serviceurl claim")

    body_service_url = str(payload.get("serviceUrl") or "").rstrip("/")
    if body_service_url.casefold() != claim_service_url.casefold():
        raise InvalidPayload("serviceUrl does not match the signed claim")
    return body_service_url


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

        service_url = _matched_service_url(payload, facts)
        # Present whenever the channel is Teams, and absent on other Bot Framework channels, so
        # it is checked when it is there rather than required. `serviceurl` is required, because
        # a caller who holds any valid Bot Framework token would otherwise choose the host the
        # bot's own bearer token is sent to.
        claim_tenant_id = str(facts.get("tid") or "")
        body_tenant_id = _body_tenant_id(payload)
        if claim_tenant_id and body_tenant_id and claim_tenant_id != body_tenant_id:
            raise InvalidPayload("channelData.tenant.id does not match the signed claim")

        activity_id = payload.get("id")
        # The token itself never leaves the scheme: the context is handed to a consumer and
        # travels into its logs and its receipts. Both values now equal the body, so a consumer
        # may read either.
        context = {
            "claim_tenant_id": claim_tenant_id,
            "claim_service_url": service_url,
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
