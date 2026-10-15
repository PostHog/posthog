import base64
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from pydantic import JsonValue

from products.cdp.backend.mcp_events import MCPEventSubscriptions
from products.cdp.backend.models.mcp_event_subscription import MCPEventSubscription


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
