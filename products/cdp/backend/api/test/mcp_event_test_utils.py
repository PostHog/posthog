import json
import base64
from typing import TypedDict, cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from pydantic import JsonValue

from products.cdp.backend.facade.mcp_events import MCPEventSubscriptionsAPI
from products.cdp.backend.mcp_events import MCPEventSubscriptions
from products.cdp.backend.models.mcp_event_subscription import MCPEventSubscription


class AuthorizedMCPEvent(TypedDict):
    body: str
    headers: dict[str, str]


class MCPEventServiceTestCase(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("products.cdp.backend.mcp_events.verify_callback"))
        self.key = "phx_mcp_events_example"
        self.callback_url = "https://example.com/callback"
        self.secret = "whsec_" + base64.b64encode(b"a" * 32).decode()
        self.principal = "personal_api_key:example"
        self.payload: dict[str, JsonValue] = {
            "arguments": {
                "project_id": self.team.pk,
                "filters": {"events": [{"id": "example_event", "type": "events"}]},
            },
            "delivery": {"url": self.callback_url, "secret": self.secret},
        }

    @property
    def service(self) -> MCPEventSubscriptions:
        return MCPEventSubscriptions(team=self.team, user=self.user, principal=self.principal)

    def subscribe(self) -> MCPEventSubscription:
        arguments = cast(dict[str, JsonValue], self.payload["arguments"])
        delivery = cast(dict[str, JsonValue], self.payload["delivery"])
        return self.service.subscribe(
            raw_filters=cast(dict[str, JsonValue], arguments["filters"]),
            url=self.callback_url,
            secret=cast(str, delivery["secret"]),
            credential=self.key,
            ttl_ms=None,
            credential_expires_at=None,
        )

    def unsubscribe(self) -> None:
        arguments = cast(dict[str, JsonValue], self.payload["arguments"])
        self.service.unsubscribe(raw_filters=cast(dict[str, JsonValue], arguments["filters"]), url=self.callback_url)

    def authorize(
        self,
        subscription: MCPEventSubscription,
        generation: object | None = None,
        filter_bytecode: list[JsonValue] | None = None,
        properties: dict[str, JsonValue] | None = None,
    ) -> AuthorizedMCPEvent:
        body = {
            "eventId": "a5524ac5-d7c5-43b6-862c-f5971da694c8",
            "name": "posthog.event_captured",
            "timestamp": timezone.now().isoformat(),
            "data": {
                "event": "example_event",
                "distinct_id": "sample-user",
                "properties": properties if properties is not None else {"plan": "enterprise"},
            },
            "cursor": None,
        }
        assert subscription.hog_function is not None
        assert subscription.hog_function.filters is not None
        return cast(
            AuthorizedMCPEvent,
            MCPEventSubscriptionsAPI(team=self.team, user=self.user, principal=self.principal).authorize_delivery(
                subscription_id=str(subscription.pk),
                generation=str(generation or subscription.generation),
                function_id=str(subscription.hog_function_id),
                filter_bytecode=filter_bytecode
                if filter_bytecode is not None
                else subscription.hog_function.filters["bytecode"],
                url=self.callback_url,
                body=json.dumps(body),
            ),
        )
