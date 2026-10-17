from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import JsonValue

from products.cdp.backend.mcp_event_delivery import MCP_CREDENTIAL_INPUT, MCP_EVENT_NAME
from products.cdp.backend.services.hog_function_persistence import upsert_hog_function

if TYPE_CHECKING:
    from posthog.models import Team, User

    from products.cdp.backend.models.hog_functions.hog_function import HogFunction
    from products.cdp.backend.models.mcp_event_subscription import MCPEventSubscription


class MCPEventDestination:
    @staticmethod
    def save(subscription: MCPEventSubscription, *, credential: str, team: Team, user: User) -> HogFunction:
        payload: dict[str, JsonValue] = {
            "name": "MCP event subscription",
            "description": "Delivers matching captured events to the subscribing MCP client.",
            "template_id": None,
            "type": "destination",
            "enabled": True,
            "hog": "mcpEventFetch(inputs.url, inputs.body);",
            "inputs_schema": [
                {"key": "url", "type": "string", "secret": True, "required": True, "label": "Callback URL"},
                {
                    "key": MCP_CREDENTIAL_INPUT,
                    "type": "string",
                    "secret": True,
                    "required": True,
                    "label": "Subscription credential",
                },
                {"key": "mcp_subscription_id", "type": "string", "required": True, "label": "Subscription ID"},
                {"key": "mcp_generation", "type": "string", "required": True, "label": "Subscription generation"},
                {"key": "body", "type": "json", "required": True, "label": "Event envelope"},
            ],
            "filters": subscription.arguments["filters"],
            "inputs": {
                "url": {"value": subscription.delivery["url"]},
                MCP_CREDENTIAL_INPUT: {"value": credential},
                "mcp_subscription_id": {"value": str(subscription.pk)},
                "mcp_generation": {"value": str(subscription.generation)},
                "body": {
                    "value": {
                        "eventId": "{event.uuid}",
                        "name": MCP_EVENT_NAME,
                        "timestamp": "{event.timestamp}",
                        "data": {
                            "event": "{event.event}",
                            "distinct_id": "{event.distinct_id}",
                            "properties": "{event.properties}",
                        },
                        "cursor": None,
                    }
                },
            },
        }
        return upsert_hog_function(
            payload, team=team, created_by=user, instance=subscription.hog_function, managed_destination="mcp"
        )
