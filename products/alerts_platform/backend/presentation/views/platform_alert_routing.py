"""Team-wide receivers, and the routes that send an alert to them by its labels.

Routing runs alongside an alert's own destinations, for every alert on the team whose labels a route
matches. Both endpoints answer only while the routing flag is on for the team.
"""

from typing import Any, Literal, cast

from django.db import models, transaction

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog import permissions
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.exceptions import as_drf_validation_error
from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models import User
from posthog.permissions import FEATURE_FLAG_REQUIRED_ERROR_CODE, get_authenticator_client

from products.alerts_platform.backend.delivery.routing import ROUTING_FLAG
from products.alerts_platform.backend.facade import api as platform_api
from products.alerts_platform.backend.facade.api import redact_destination_data
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertDestinationValidationError,
    AlertEventKind,
    AlertReceiverEdit,
    AlertRouteEdit,
    DestinationType,
    RouteMatcher,
    StoredAlertReceiver,
    StoredAlertRoute,
    UnknownAlertRouting,
)
from products.alerts_platform.backend.logic.alert_routing import ROUTABLE_DESTINATION_TYPES
from products.alerts_platform.backend.presentation.views.platform_alert import PLATFORM_ALERTS_FLAG
from products.alerts_platform.backend.presentation.views.platform_alert_destinations import (
    PlatformAlertDestinationEventKind,
    destination_data,
)

# TextChoices supports this functional API at runtime, but its type stubs only describe member
# construction. The OpenAPI enum is named after this class.
AlertReceiverType = cast(Any, models.TextChoices)(
    "AlertReceiverType",
    [(member.name, (member.value, member.label)) for member in ROUTABLE_DESTINATION_TYPES],
)
_DESTINATION_FIELDS = ("type", "slack_workspace_id", "slack_channel_id", "slack_channel_name", "webhook_url")


class PlatformAlertRoutingFlagPermission(BasePermission):
    message = f"This action requires feature flags {PLATFORM_ALERTS_FLAG!r} and {ROUTING_FLAG!r}."
    code = FEATURE_FLAG_REQUIRED_ERROR_CODE

    def has_permission(self, request: Request, view: APIView) -> bool:
        assert isinstance(view, TeamAndOrgViewSetMixin)
        return all(
            permissions.posthog_feature_flag_enabled(
                flag,
                str(cast(User, request.user).distinct_id),
                organization_id=view.team.organization_id,
                team_id=view.team.id,
                caller_properties=get_authenticator_client(getattr(request, "successful_authenticator", None)),
            )
            for flag in (PLATFORM_ALERTS_FLAG, ROUTING_FLAG)
        )


class AlertReceiverSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the receiver. Routes name it in receiver_id.")
    name = serializers.CharField(help_text="Name of the receiver, unique in the project.")
    type = serializers.ChoiceField(choices=AlertReceiverType.choices, help_text="Notification destination type.")
    enabled = serializers.BooleanField(
        help_text="Whether routes send to this receiver. A disabled receiver gets nothing."
    )
    route_count = serializers.IntegerField(
        help_text="How many routes send to this receiver. Deleting the receiver deletes them."
    )
    slack_workspace_id = serializers.IntegerField(
        required=False, help_text="Integration ID of the Slack workspace. Set when type=slack."
    )
    slack_channel_id = serializers.CharField(required=False, help_text="Slack channel ID. Set when type=slack.")
    slack_channel_name = serializers.CharField(
        required=False, help_text="Human-readable Slack channel name. Set when type=slack."
    )
    webhook_url = serializers.CharField(
        required=False,
        help_text="Webhook endpoint reduced to scheme and host. The path, query and userinfo carry the secret.",
    )


class AlertReceiverWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="Name of the receiver, unique in the project.")
    enabled = serializers.BooleanField(
        required=False, help_text="Whether routes send to this receiver. Defaults to true."
    )
    type = serializers.ChoiceField(choices=AlertReceiverType.choices, help_text="Notification destination type.")
    slack_workspace_id = serializers.IntegerField(
        required=False, help_text="Integration ID for the Slack workspace. Required when type=slack."
    )
    slack_channel_id = serializers.CharField(required=False, help_text="Slack channel ID. Required when type=slack.")
    slack_channel_name = serializers.CharField(
        required=False, allow_blank=True, help_text="Human-readable channel name for display."
    )
    webhook_url = serializers.URLField(
        required=False,
        help_text="HTTPS endpoint to post to. Required for webhook, teams and discord. Send it again on every "
        "update that changes the destination, because reads return it redacted.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        sent = [key for key in _DESTINATION_FIELDS if key in attrs]
        if sent and "type" not in attrs:
            raise ValidationError({"type": "Send the type with the destination fields it goes with."})
        return {
            "name": attrs.get("name"),
            "enabled": attrs.get("enabled"),
            "data": destination_data(attrs) if sent else None,
        }


class AlertRouteMatcherSerializer(serializers.Serializer):
    label = serializers.CharField(help_text="Name of an alert label, such as team.")
    value = serializers.CharField(help_text="The value the label must equal, such as checkout.")


class AlertRouteSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="ID of the route.")
    receiver_id = serializers.UUIDField(help_text="ID of the receiver this route sends to.")
    matchers = AlertRouteMatcherSerializer(
        many=True,
        required=False,
        help_text="Label conditions, all of which must hold for an alert to match. An empty list matches "
        "every alert in the project.",
    )
    event_kinds = serializers.ListField(
        child=serializers.ChoiceField(choices=PlatformAlertDestinationEventKind.choices),
        required=False,
        min_length=1,
        help_text="The alert transitions the receiver hears about through this route. Defaults to every kind.",
    )
    enabled = serializers.BooleanField(required=False, help_text="Whether this route sends. Defaults to true.")


def _serialized_receiver(receiver: StoredAlertReceiver) -> dict[str, Any]:
    return {
        "id": receiver.id,
        "name": receiver.name,
        "enabled": receiver.enabled,
        "route_count": receiver.route_count,
        **redact_destination_data(receiver.data),
    }


def _serialized_route(route: StoredAlertRoute) -> dict[str, Any]:
    return {
        "id": route.id,
        "receiver_id": route.receiver_id,
        "matchers": [{"label": matcher.label, "value": matcher.value} for matcher in route.matchers],
        "event_kinds": [kind.value for kind in route.event_kinds],
        "enabled": route.enabled,
    }


_NOT_FOUND = OpenApiResponse(description="No receiver or route with this ID in the project.")
_INVALID = OpenApiResponse(description="The settings are invalid.")


class _RoutingViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "alert"
    permission_classes = [PlatformAlertRoutingFlagPermission]
    pagination_class = None

    def _track(self, event: str, properties: dict[str, Any]) -> None:
        # Robust, so an analytics failure, such as a malformed Referer, cannot fail a write that committed.
        transaction.on_commit(
            lambda: report_user_action(
                cast(User, self.request.user), event, properties, team=self.team, request=self.request
            ),
            robust=True,
        )


class PlatformAlertReceiverViewSet(_RoutingViewSet):
    serializer_class = AlertReceiverSerializer

    def _check_slack_workspace(self, data: AlertDestinationData | None) -> None:
        if data is None or data["type"] != DestinationType.SLACK:
            return
        # The accessor delivery sends through, so a receiver it would refuse is never saved.
        try:
            IntegrationManager.slack.oauth.get(self.team_id, data["slack_workspace_id"])
        except IntegrationNotFound:
            raise ValidationError({"slack_workspace_id": "Choose a Slack workspace connected to this project."})

    @extend_schema(responses=AlertReceiverSerializer(many=True), description="List the project's alert receivers.")
    def list(self, request: Request, **kwargs: Any) -> Response:
        receivers = platform_api.list_alert_receivers(team_id=self.team_id)
        return Response(AlertReceiverSerializer([_serialized_receiver(r) for r in receivers], many=True).data)

    @extend_schema(
        request=AlertReceiverWriteSerializer,
        responses={201: AlertReceiverSerializer, 400: _INVALID},
        description="Add a receiver that routes can send alerts to.",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        serializer = AlertReceiverWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        edit = AlertReceiverEdit(**serializer.validated_data)
        self._check_slack_workspace(edit.data)
        try:
            created = platform_api.create_alert_receiver(team_id=self.team_id, edit=edit)
        except AlertDestinationValidationError as error:
            raise as_drf_validation_error(error)
        self._track("alert receiver created", {"type": created.data["type"]})
        return Response(AlertReceiverSerializer(_serialized_receiver(created)).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=AlertReceiverWriteSerializer(partial=True),
        responses={200: AlertReceiverSerializer, 400: _INVALID, 404: _NOT_FOUND},
        description="Change a receiver. Destination fields replace the stored destination and need the type.",
    )
    def partial_update(self, request: Request, pk: str, **kwargs: Any) -> Response:
        receiver_id = serializers.UUIDField().run_validation(pk)
        serializer = AlertReceiverWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        edit = AlertReceiverEdit(**serializer.validated_data)
        self._check_slack_workspace(edit.data)
        try:
            updated = platform_api.update_alert_receiver(team_id=self.team_id, receiver_id=receiver_id, edit=edit)
        except UnknownAlertRouting:
            raise NotFound()
        except AlertDestinationValidationError as error:
            raise as_drf_validation_error(error)
        self._track("alert receiver updated", {"type": updated.data["type"]})
        return Response(AlertReceiverSerializer(_serialized_receiver(updated)).data)

    @extend_schema(
        responses={204: OpenApiResponse(description="The receiver and its routes are deleted."), 404: _NOT_FOUND},
        description="Delete a receiver and every route that sends to it.",
    )
    def destroy(self, request: Request, pk: str, **kwargs: Any) -> Response:
        receiver_id = serializers.UUIDField().run_validation(pk)
        try:
            platform_api.delete_alert_receiver(team_id=self.team_id, receiver_id=receiver_id)
        except UnknownAlertRouting:
            raise NotFound()
        self._track("alert receiver deleted", {})
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlatformAlertRouteViewSet(_RoutingViewSet):
    serializer_class = AlertRouteSerializer

    def _edit(self, request: Request, *, partial: bool) -> AlertRouteEdit:
        serializer = AlertRouteSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        attrs = serializer.validated_data
        matchers = attrs.get("matchers")
        event_kinds = attrs.get("event_kinds")
        return AlertRouteEdit(
            receiver_id=attrs.get("receiver_id"),
            matchers=None if matchers is None else tuple(RouteMatcher(**matcher) for matcher in matchers),
            event_kinds=None if event_kinds is None else tuple(AlertEventKind(kind) for kind in event_kinds),
            enabled=attrs.get("enabled"),
        )

    def _track_route(self, action: Literal["created", "updated"], route: StoredAlertRoute) -> None:
        self._track(
            f"alert route {action}",
            {"matcher_count": len(route.matchers), "event_kinds": [kind.value for kind in route.event_kinds]},
        )

    @extend_schema(
        responses=AlertRouteSerializer(many=True),
        description="List the project's alert routes, in the order delivery reads them.",
    )
    def list(self, request: Request, **kwargs: Any) -> Response:
        routes = platform_api.list_alert_routes(team_id=self.team_id)
        return Response(AlertRouteSerializer([_serialized_route(r) for r in routes], many=True).data)

    @extend_schema(
        request=AlertRouteSerializer,
        responses={201: AlertRouteSerializer, 400: _INVALID},
        description="Add a route. Every alert whose labels match it also sends to its receiver.",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        edit = self._edit(request, partial=False)
        try:
            created = platform_api.create_alert_route(team_id=self.team_id, edit=edit)
        except AlertDestinationValidationError as error:
            raise as_drf_validation_error(error)
        self._track_route("created", created)
        return Response(AlertRouteSerializer(_serialized_route(created)).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=AlertRouteSerializer(partial=True),
        responses={200: AlertRouteSerializer, 400: _INVALID, 404: _NOT_FOUND},
        description="Change a route. Fields left out keep their stored value.",
    )
    def partial_update(self, request: Request, pk: str, **kwargs: Any) -> Response:
        route_id = serializers.UUIDField().run_validation(pk)
        edit = self._edit(request, partial=True)
        try:
            updated = platform_api.update_alert_route(team_id=self.team_id, route_id=route_id, edit=edit)
        except UnknownAlertRouting:
            raise NotFound()
        except AlertDestinationValidationError as error:
            raise as_drf_validation_error(error)
        self._track_route("updated", updated)
        return Response(AlertRouteSerializer(_serialized_route(updated)).data)

    @extend_schema(
        responses={204: OpenApiResponse(description="The route is deleted."), 404: _NOT_FOUND},
        description="Delete a route.",
    )
    def destroy(self, request: Request, pk: str, **kwargs: Any) -> Response:
        route_id = serializers.UUIDField().run_validation(pk)
        try:
            platform_api.delete_alert_route(team_id=self.team_id, route_id=route_id)
        except UnknownAlertRouting:
            raise NotFound()
        self._track("alert route deleted", {})
        return Response(status=status.HTTP_204_NO_CONTENT)
