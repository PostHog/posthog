"""Slack Events API and interactivity deliveries.

Slack wraps the interesting event in an envelope, so the event type a consumer registers for
is the inner `event.type`, not the envelope's. The `url_verification` handshake is answered
before any consumer runs, because Slack wants the challenge echoed in the body.

Interactive components arrive at a second URL, as a form, with a payload shape of their own.
They are a second app here rather than more event types on `supporthog`, so each endpoint's
consumers are validated against the type list of the endpoint they actually run on.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone

from posthog.ingress.contracts import ProviderSpec, WebhookDelivery
from posthog.ingress.providers import InvalidPayload, WebhookProvider
from posthog.ingress.verify.schemes import HmacSha256, SignatureScheme

SLACK_EVENT_TYPES = frozenset(
    {
        "app_mention",
        "link_shared",
        "message",
        "reaction_added",
        "member_joined_channel",
        "member_left_channel",
    }
)

SLACK_INTERACTIVITY_APP = "supporthog_interactivity"

SLACK_INTERACTIVITY_TYPES = frozenset(
    {
        "block_actions",
        "block_suggestion",
        "message_action",
        "shortcut",
        "view_closed",
        "view_submission",
    }
)

# Slack signs the raw form body, so a consumer that keys idempotency on the bytes Slack signed
# cannot rebuild them from the parsed mapping: key order and separators are already lost. The
# `payload` field rides along under this key, and the consumer removes it before it stores the
# payload.
SLACK_RAW_PAYLOAD_KEY = "_posthog_raw_payload"

SPECS = (
    ProviderSpec(provider="slack", app="supporthog", event_types=SLACK_EVENT_TYPES),
    ProviderSpec(provider="slack", app=SLACK_INTERACTIVITY_APP, event_types=SLACK_INTERACTIVITY_TYPES),
)


def _delivery_context(request: HttpRequest, *, slack_team_id: str) -> dict[str, str]:
    return {
        "slack_team_id": slack_team_id,
        # Slack retries a delivery it thinks failed and says so in these headers, which
        # consumers record on their receipt.
        "retry_num": request.headers.get("X-Slack-Retry-Num", ""),
        "retry_reason": request.headers.get("X-Slack-Retry-Reason", ""),
    }


class SlackProvider(WebhookProvider):
    provider = "slack"
    # Slack redelivers on a non-2xx, so a delivery ingress cannot vouch for must not be receipted:
    # a workspace ownership lookup that raised or hit its timeout, a forward to the owning region
    # that never landed, and a receipt write that raised all lose the 202.
    retry_status = 502

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

    def deliveries(self, request: HttpRequest, payload: Any, facts: Mapping[str, Any]) -> Sequence[WebhookDelivery]:
        if not isinstance(payload, Mapping) or payload.get("type") != "event_callback":
            return ()
        event = payload.get("event")
        event = event if isinstance(event, Mapping) else {}
        event_id = payload.get("event_id")
        return (
            WebhookDelivery(
                provider=self.provider,
                app=self.app,
                delivery_id=str(event_id) if isinstance(event_id, str) and event_id else None,
                event_type=str(event.get("type", "")),
                payload=payload,
                received_at=timezone.now(),
                context=_delivery_context(request, slack_team_id=str(payload.get("team_id") or "")),
            ),
        )


class SlackInteractivityProvider(SlackProvider):
    """Interactive components: the same app registration and signing secret, a form body.

    The payload shape is its own: no envelope, so the event type is the payload's own `type`,
    and the workspace is `team.id` rather than `team_id`.
    """

    def __init__(self, *, secret_getter: Callable[[], str | None]) -> None:
        super().__init__(app=SLACK_INTERACTIVITY_APP, secret_getter=secret_getter)

    def parse(self, request: HttpRequest) -> Any:
        """The JSON Slack put in the form's `payload` field, plus the field itself.

        Reading the form consumes the request stream under ASGI, which would leave the
        signature check without the raw bytes. The view verifies before it parses, so by the
        time this runs the raw body has been read.
        """
        raw_payload = request.POST.get("payload")
        if raw_payload is None:
            raise InvalidPayload("no payload field in the form body")
        try:
            # RecursionError: deeply nested JSON must answer 400, not 500.
            payload = json.loads(raw_payload)
        except (json.JSONDecodeError, RecursionError) as error:
            raise InvalidPayload(str(error)) from error
        if not isinstance(payload, dict):
            raise InvalidPayload("payload field is not a JSON object")
        return {**payload, SLACK_RAW_PAYLOAD_KEY: raw_payload}

    def deliveries(self, request: HttpRequest, payload: Any, facts: Mapping[str, Any]) -> Sequence[WebhookDelivery]:
        if not isinstance(payload, Mapping):
            return ()
        team = payload.get("team")
        slack_team_id = str(team.get("id") or "") if isinstance(team, Mapping) else ""
        return (
            WebhookDelivery(
                provider=self.provider,
                app=self.app,
                # Slack sends no id with an interactive payload, so dedup has nothing to key on.
                # Idempotency is the consumer's own source id.
                delivery_id=None,
                event_type=str(payload.get("type", "")),
                payload=payload,
                received_at=timezone.now(),
                context=_delivery_context(request, slack_team_id=slack_team_id),
            ),
        )


def build_slack_provider(*, secret_getter: Callable[[], str | None], app: str = "supporthog") -> SlackProvider:
    """The signing secret lives with the product that owns the Slack app, so it is passed in."""
    return SlackProvider(app=app, secret_getter=secret_getter)


def build_slack_interactivity_provider(*, secret_getter: Callable[[], str | None]) -> SlackInteractivityProvider:
    return SlackInteractivityProvider(secret_getter=secret_getter)
