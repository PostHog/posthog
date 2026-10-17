from typing import cast

from django.db.models import TextChoices

import posthoganalytics
from drf_spectacular.utils import extend_schema
from pydantic import JsonValue
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.auth import (
    DelegatedOAuthAccessTokenAuthentication,
    DelegatedPersonalAPIKeyAuthentication,
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
)
from posthog.models import User

from products.cdp.backend.facade.mcp_event_types import (
    MCPCallbackError,
    MCPEventSubscriptionNotFoundError,
    MCPEventSubscriptionPermissionError,
)
from products.cdp.backend.facade.mcp_events import (
    MAX_TTL_MS,
    MCP_EVENT_NAME,
    MCPEventSubscriptionsAPI,
    validate_mcp_callback_url,
    validate_mcp_signing_secret,
)
from products.cdp.backend.presentation.serializers import HogFunctionFiltersSerializer, MCPEventEnvelopeSerializer


class MCPEventSource(TextChoices):
    EVENTS = "events", "events"


class MCPEventFiltersSerializer(HogFunctionFiltersSerializer):
    source = serializers.ChoiceField(
        choices=MCPEventSource.choices,
        required=False,
        default=MCPEventSource.EVENTS,
        help_text="Captured PostHog events. Use events.",
    )

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        for key in ("bytecode", "bytecode_error", "bytecode_contract", "transpiled", "data_warehouse"):
            fields.pop(key, None)
        descriptions = {
            "events": 'Captured event entries combined with OR. Example: [{"id": "survey sent", "type": "events", "properties": [{"key": "rating", "type": "event", "operator": "lt", "value": 3}]}].',
            "actions": 'Saved action entries combined with the event entries using OR. Example: [{"id": "123", "type": "actions"}].',
            "properties": 'Property conditions applied to all selected events. Example: [{"key": "plan", "type": "event", "operator": "exact", "value": "enterprise"}].',
            "filter_test_accounts": "Apply the project's existing test-account exclusions.",
        }
        for key, description in descriptions.items():
            fields[key].help_text = description
        return fields

    def to_internal_value(self, data: object) -> dict[str, JsonValue]:
        if not isinstance(data, dict):
            raise ValidationError("Send event filters as a JSON object.")
        unknown = set(data) - set(self.fields)
        if unknown:
            raise ValidationError(
                dict.fromkeys(sorted(unknown), "This field is not supported in subscription filters.")
            )
        return super().to_internal_value(data)

    def validate(self, data: dict[str, JsonValue]) -> dict[str, JsonValue]:
        # The service validates live filters; cancellation must also accept filters for deleted actions.
        return data


class MCPEventArgumentsSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(min_value=1, help_text="Project whose captured events should be monitored.")
    filters = MCPEventFiltersSerializer(
        help_text="Normal real-time destination filters. Preview the filters before subscribing."
    )

    def validate_project_id(self, value: int) -> int:
        if value != self.context["get_team"]().pk:
            raise ValidationError("Use the project in this endpoint's URL.")
        return value


class MCPEventIdentityArgumentsSerializer(MCPEventArgumentsSerializer):
    filters = MCPEventFiltersSerializer(help_text="Original event filters, including filters for deleted resources.")


class MCPEventWebhookSerializer(serializers.Serializer):
    mode = serializers.CharField(help_text="Delivery mode. Use webhook.")
    url = serializers.URLField(max_length=4096, help_text="HTTPS callback supplied by the receiving MCP client.")
    secret = serializers.CharField(
        write_only=True, max_length=128, trim_whitespace=False, help_text="Client-supplied whsec_ signing secret."
    )

    def validate_mode(self, value: str) -> str:
        if value != "webhook":
            raise ValidationError("Use webhook delivery.")
        return value

    def validate_url(self, value: str) -> str:
        return validate_mcp_callback_url(value)

    def validate_secret(self, value: str) -> str:
        return validate_mcp_signing_secret(value)


class MCPEventSubscribeSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Event type. Use posthog.event_captured.")
    arguments = MCPEventArgumentsSerializer(help_text="Project and event filters for this subscription.")
    delivery = MCPEventWebhookSerializer(help_text="Callback and signing information supplied by the client.")
    ttl_ms = serializers.IntegerField(
        min_value=1000,
        required=False,
        allow_null=True,
        default=MAX_TTL_MS,
        help_text="Requested lifetime in milliseconds. The server grants a finite lifetime of at most 24 hours.",
    )
    cursor = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Replay is unavailable. Use null to receive future events.",
    )

    def validate_name(self, value: str) -> str:
        if value != MCP_EVENT_NAME:
            raise ValidationError("Use posthog.event_captured.")
        return value

    def validate_cursor(self, value: str | None) -> str | None:
        if value is not None:
            raise ValidationError("This event does not support replay. Use null.")
        return value


class MCPEventUnsubscribeDeliverySerializer(serializers.Serializer):
    mode = serializers.CharField(help_text="Delivery mode. Use webhook.")
    url = serializers.URLField(max_length=4096, help_text="Original callback URL supplied when subscribing.")

    def validate_mode(self, value: str) -> str:
        if value != "webhook":
            raise ValidationError("Use webhook delivery.")
        return value

    def validate_url(self, value: str) -> str:
        return validate_mcp_callback_url(value)


class MCPEventUnsubscribeSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Event type. Use posthog.event_captured.")
    arguments = MCPEventIdentityArgumentsSerializer(help_text="Original project and event filters.")
    delivery = MCPEventUnsubscribeDeliverySerializer(help_text="Original callback identity.")

    def validate_name(self, value: str) -> str:
        if value != MCP_EVENT_NAME:
            raise ValidationError("Use posthog.event_captured.")
        return value


class MCPEventSubscriptionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Subscription ID supplied to the receiving MCP client.")
    arguments = MCPEventArgumentsSerializer(read_only=True)
    callback_host = serializers.CharField(
        read_only=True, help_text="Callback hostname. Paths and signing secrets are hidden."
    )
    expires_at = serializers.DateTimeField(
        read_only=True, help_text="Time when this subscription stops delivering events."
    )
    active = serializers.BooleanField(read_only=True, help_text="Whether this subscription is enabled.")
    created_at = serializers.DateTimeField(read_only=True, help_text="Time when this subscription was created.")


class MCPEventPreviewSerializer(serializers.Serializer):
    filters = MCPEventFiltersSerializer(read_only=True)
    examples = MCPEventEnvelopeSerializer(many=True, help_text="Up to five matching events from the lookback window.")
    lookback_days = serializers.IntegerField(help_text="Number of days searched for examples.")
    sample_limit = serializers.IntegerField(help_text="Maximum number of examples. This is not a total event count.")


class MCPEventDeliveryRequestSerializer(serializers.Serializer):
    filter_bytecode = serializers.ListField(
        child=serializers.JSONField(), help_text="Compiled filter that matched the queued event."
    )
    generation = serializers.UUIDField(help_text="Subscription lifecycle generation carried by the queued destination.")
    function_id = serializers.UUIDField(help_text="Managed destination that queued the event.")
    url = serializers.URLField(max_length=4096, help_text="Callback URL carried by the queued destination.")
    body = serializers.CharField(
        max_length=256 * 1024,
        trim_whitespace=False,
        help_text="Exact JSON event body awaiting authorization and signing.",
    )


class MCPEventDeliveryResponseSerializer(serializers.Serializer):
    body = serializers.CharField(help_text="Authorized serialized event body.")
    headers = serializers.DictField(
        child=serializers.CharField(),
        help_text="Fresh signing headers for this delivery. Signing secrets are never returned.",
    )


class MCPEventEmptySerializer(serializers.Serializer):
    pass


class MCPEventSubscriptionPagination(LimitOffsetPagination):
    default_limit = 100
    max_limit = 100


class MCPEventDeliveryThrottle(UserRateThrottle):
    scope = "mcp_event_delivery"
    rate = "600/min"


class MCPEventSubscriptionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    pagination_class = MCPEventSubscriptionPagination
    scope_object = "mcp_event_subscription"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["subscribe", "unsubscribe"]
    serializer_class = MCPEventSubscriptionSerializer

    def get_serializer_context(self) -> dict[str, object]:
        return {
            **super().get_serializer_context(),
            "function_type": "destination",
            "function_will_be_enabled": True,
        }

    def initial(self, request: Request, *args: object, **kwargs: object) -> None:
        super().initial(request, *args, **kwargs)
        if not posthoganalytics.feature_enabled(
            "mcp-events",
            cast(User, request.user).distinct_id or str(request.user.pk),
            groups={"organization": str(self.team.organization_id)},
            send_feature_flag_events=False,
        ):
            raise NotFound("MCP event subscriptions are not enabled for this account.")

    def _principal(self, request: Request) -> str:
        authenticator = request.successful_authenticator
        if isinstance(authenticator, (DelegatedOAuthAccessTokenAuthentication, DelegatedPersonalAPIKeyAuthentication)):
            raise PermissionDenied(
                "Use the original OAuth access token or personal API key directly to manage subscriptions."
            )
        if isinstance(authenticator, OAuthAccessTokenAuthentication):
            return f"oauth:{request.user.pk}:{authenticator.access_token.application_id}"
        if isinstance(authenticator, PersonalAPIKeyAuthentication):
            return f"personal_api_key:{request.user.pk}:{authenticator.personal_api_key.pk}"
        raise PermissionDenied("Connect using an OAuth token or personal API key to manage subscriptions.")

    def _service(self, request: Request) -> MCPEventSubscriptionsAPI:
        return MCPEventSubscriptionsAPI(
            team=self.team, user=cast(User, request.user), principal=self._principal(request)
        )

    @extend_schema(responses=MCPEventSubscriptionSerializer(many=True))
    def list(self, request: Request, *args: object, **kwargs: object) -> Response:
        service = MCPEventSubscriptionsAPI(team=self.team, user=cast(User, request.user), principal="")
        paginator = self.paginator
        assert isinstance(paginator, LimitOffsetPagination)
        paginator.request = request
        paginator.limit = paginator.get_limit(request) or 100
        paginator.offset = paginator.get_offset(request)
        page = service.list_subscriptions(limit=paginator.limit, offset=paginator.offset)
        paginator.count = page.count
        return paginator.get_paginated_response(self.get_serializer(page.results, many=True).data)

    @extend_schema(responses=MCPEventSubscriptionSerializer)
    def retrieve(self, request: Request, *args: object, **kwargs: object) -> Response:
        service = MCPEventSubscriptionsAPI(team=self.team, user=cast(User, request.user), principal="")
        try:
            subscription = service.get(str(kwargs["pk"]))
        except MCPEventSubscriptionNotFoundError:
            raise NotFound() from None
        return Response(self.get_serializer(subscription).data)

    @extend_schema(
        operation_id="mcp_event_subscriptions_preview",
        request=MCPEventArgumentsSerializer,
        responses=MCPEventPreviewSerializer,
    )
    @action(detail=False, methods=["POST"], required_scopes=["query:read"])
    def preview(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = MCPEventArgumentsSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        service = MCPEventSubscriptionsAPI(team=self.team, user=cast(User, request.user), principal="")
        result = service.preview(serializer.validated_data["filters"])
        return Response(MCPEventPreviewSerializer(result, context=self.get_serializer_context()).data)

    @extend_schema(request=MCPEventSubscribeSerializer, responses=MCPEventSubscriptionSerializer)
    @action(detail=False, methods=["POST"], required_scopes=["mcp_event_subscription:write", "query:read"])
    def subscribe(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = MCPEventSubscribeSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        authorization = request.headers.get("Authorization", "").split()
        if len(authorization) != 2 or authorization[0].lower() != "bearer":
            raise PermissionDenied("Send the subscription credential in a Bearer Authorization header.")
        try:
            subscription = self._service(request).subscribe(
                raw_filters=data["arguments"]["filters"],
                url=data["delivery"]["url"],
                secret=data["delivery"]["secret"],
                credential=authorization[1],
                ttl_ms=data["ttl_ms"],
                credential_expires_at=(
                    request.successful_authenticator.access_token.expires
                    if isinstance(request.successful_authenticator, OAuthAccessTokenAuthentication)
                    else None
                ),
            )
        except MCPCallbackError as error:
            raise ValidationError({"callback": {"reason": error.reason, "detail": str(error)}}) from None
        return Response(self.get_serializer(subscription).data)

    @extend_schema(request=MCPEventUnsubscribeSerializer, responses=MCPEventEmptySerializer)
    @action(detail=False, methods=["POST"], required_scopes=["mcp_event_subscription:write"])
    def unsubscribe(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = MCPEventUnsubscribeSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        self._service(request).unsubscribe(raw_filters=data["arguments"]["filters"], url=data["delivery"]["url"])
        return Response(MCPEventEmptySerializer({}).data)

    @extend_schema(request=MCPEventDeliveryRequestSerializer, responses=MCPEventDeliveryResponseSerializer)
    @action(
        detail=True,
        methods=["POST"],
        required_scopes=["mcp_event_subscription:write", "query:read"],
        throttle_classes=[MCPEventDeliveryThrottle],
    )
    def authorize_delivery(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = MCPEventDeliveryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = self._service(request).authorize_delivery(
                subscription_id=str(kwargs["pk"]),
                generation=str(data["generation"]),
                body=data["body"],
                url=data["url"],
                function_id=str(data["function_id"]),
                filter_bytecode=data["filter_bytecode"],
            )
        except MCPEventSubscriptionNotFoundError:
            raise NotFound() from None
        except MCPEventSubscriptionPermissionError as error:
            raise PermissionDenied(str(error)) from None
        return Response(MCPEventDeliveryResponseSerializer(result).data)
