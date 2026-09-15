"""Slack Events API deliveries.

Slack wraps the interesting event in an envelope, so the event type a consumer registers for
is the inner `event.type`, not the envelope's. The `url_verification` handshake is answered
before any consumer runs, because Slack wants the challenge echoed in the body.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone

from posthog.ingress.contracts import ProviderSpec, WebhookDelivery
from posthog.ingress.providers import WebhookProvider
from posthog.ingress.verify.schemes import HmacSha256, SignatureScheme

SLACK_EVENT_TYPES = frozenset(
    {
        "app_mention",
        "message",
        "reaction_added",
        "member_joined_channel",
        "member_left_channel",
    }
)

SPECS = (ProviderSpec(provider="slack", app="supporthog", event_types=SLACK_EVENT_TYPES),)


class SlackProvider(WebhookProvider):
    provider = "slack"

    def __init__(self, *, app: str = "supporthog", secret_getter: Callable[[], str | None]) -> None:
        self.app = app
        self._scheme = HmacSha256(
            secret_getter=secret_getter,
            signature_header="X-Slack-Signature",
            prefix="v0=",
            signed_input="v0_timestamp_body",
            timestamp_header="X-Slack-Request-Timestamp",
            # Slack's own guidance: drop anything older than five minutes. The tighter future
            # bound is clock skew only, so a replayed future timestamp buys almost nothing.
            timestamp_max_age_seconds=300,
            timestamp_max_future_seconds=60,
        )

    def scheme(self) -> SignatureScheme:
        return self._scheme

    def pre_dispatch_response(self, request: HttpRequest, payload: Any) -> HttpResponse | None:
        if isinstance(payload, Mapping) and payload.get("type") == "url_verification":
            return JsonResponse({"challenge": str(payload.get("challenge", ""))})
        return None

    def deliveries(self, request: HttpRequest, payload: Any) -> Sequence[WebhookDelivery]:
        if not isinstance(payload, Mapping) or payload.get("type") != "event_callback":
            return ()
        event = payload.get("event")
        event = event if isinstance(event, Mapping) else {}
        event_id = payload.get("event_id")
        context = {
            "slack_team_id": str(payload.get("team_id") or ""),
            # Slack retries a delivery it thinks failed and says so in these headers, which
            # consumers record on their receipt.
            "retry_num": request.headers.get("X-Slack-Retry-Num", ""),
            "retry_reason": request.headers.get("X-Slack-Retry-Reason", ""),
        }
        return (
            WebhookDelivery(
                provider=self.provider,
                app=self.app,
                delivery_id=str(event_id) if isinstance(event_id, str) and event_id else None,
                event_type=str(event.get("type", "")),
                payload=payload,
                received_at=timezone.now(),
                context=context,
            ),
        )


def build_slack_provider(*, secret_getter: Callable[[], str | None], app: str = "supporthog") -> SlackProvider:
    """The signing secret lives with the product that owns the Slack app, so it is passed in."""
    return SlackProvider(app=app, secret_getter=secret_getter)
