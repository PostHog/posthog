from datetime import datetime
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import JsonValue

from posthog.models import Team, User

from products.cdp.backend.facade.mcp_event_types import (
    MCPEventSubscriptionNotFoundError,
    MCPEventSubscriptionPage,
    MCPEventSubscriptionPermissionError,
    MCPEventSubscriptionRecord,
)
from products.cdp.backend.mcp_event_delivery import (
    MCP_EVENT_NAME as MCP_EVENT_NAME,
    signing_key,
    validate_callback_url,
)
from products.cdp.backend.mcp_events import (
    MAX_TTL_MS as MAX_TTL_MS,
    MCPEventSubscriptions,
)
from products.cdp.backend.models.mcp_event_subscription import MCPEventSubscription


def validate_mcp_callback_url(url: str) -> str:
    return validate_callback_url(url)


def validate_mcp_signing_secret(secret: str) -> str:
    signing_key(secret)
    return secret


def _subscription_record(subscription: MCPEventSubscription) -> MCPEventSubscriptionRecord:
    return MCPEventSubscriptionRecord(
        id=subscription.id,
        arguments=cast(dict[str, JsonValue], subscription.arguments),
        callback_host=urlsplit(subscription.delivery["url"]).hostname or "",
        expires_at=subscription.expires_at,
        active=subscription.active,
        created_at=subscription.created_at,
    )


class MCPEventSubscriptionsAPI:
    def __init__(self, *, team: Team, user: User, principal: str) -> None:
        self._service = MCPEventSubscriptions(team=team, user=user, principal=principal)

    def _get_subscription(self, subscription_id: str) -> MCPEventSubscription:
        try:
            subscription_uuid = UUID(subscription_id)
        except ValueError:
            raise MCPEventSubscriptionNotFoundError from None
        subscription = (
            MCPEventSubscription.objects.for_team(self._service.team.pk)
            .select_related("hog_function")
            .filter(created_by=self._service.user, pk=subscription_uuid)
            .first()
        )
        if subscription is None:
            raise MCPEventSubscriptionNotFoundError
        return subscription

    def list_subscriptions(self, *, limit: int, offset: int) -> MCPEventSubscriptionPage:
        subscriptions = (
            MCPEventSubscription.objects.for_team(self._service.team.pk)
            .filter(created_by=self._service.user)
            .order_by("-created_at", "-id")
        )
        return MCPEventSubscriptionPage(
            count=subscriptions.count(),
            results=[_subscription_record(subscription) for subscription in subscriptions[offset : offset + limit]],
        )

    def get(self, subscription_id: str) -> MCPEventSubscriptionRecord:
        return _subscription_record(self._get_subscription(subscription_id))

    def preview(self, raw_filters: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return self._service.preview(raw_filters)

    def subscribe(
        self,
        *,
        raw_filters: dict[str, JsonValue],
        url: str,
        secret: str,
        credential: str,
        ttl_ms: int | None,
        credential_expires_at: datetime | None,
    ) -> MCPEventSubscriptionRecord:
        subscription = self._service.subscribe(
            raw_filters=raw_filters,
            url=url,
            secret=secret,
            credential=credential,
            ttl_ms=ttl_ms,
            credential_expires_at=credential_expires_at,
        )
        return _subscription_record(subscription)

    def unsubscribe(self, *, raw_filters: dict[str, JsonValue], url: str) -> None:
        self._service.unsubscribe(raw_filters=raw_filters, url=url)

    def authorize_delivery(
        self,
        *,
        subscription_id: str,
        generation: str,
        body: str,
        url: str,
        function_id: str,
        filter_bytecode: list[JsonValue],
    ) -> dict[str, JsonValue]:
        subscription = self._get_subscription(subscription_id)
        if subscription.principal != self._service.principal:
            raise MCPEventSubscriptionPermissionError("Use the credential that owns this subscription.")
        return self._service.authorize_delivery(
            subscription=subscription,
            generation=generation,
            body=body,
            url=url,
            function_id=function_id,
            filter_bytecode=filter_bytecode,
        )
