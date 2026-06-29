from __future__ import annotations

from typing import cast

from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.team.team import Team
from posthog.models.user import User

from products.billing_alerts.backend.facade import api as billing_alerts_api
from products.billing_alerts.backend.facade.api import BillingAlertConfiguration
from products.billing_alerts.backend.presentation.permissions import IsOrganizationAdminOrOwner
from products.billing_alerts.backend.presentation.serializers import (
    BillingAlertCheckNowResponseSerializer,
    BillingAlertConfigurationSerializer,
    BillingAlertCreateDestinationSerializer,
    BillingAlertDeleteDestinationSerializer,
    BillingAlertDestinationResponseSerializer,
    BillingAlertEventSerializer,
)


@extend_schema(tags=["billing"])
class BillingAlertViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = billing_alerts_api.billing_alert_configuration_queryset()
    serializer_class = BillingAlertConfigurationSerializer
    lookup_field = "id"
    permission_classes = [IsOrganizationAdminOrOwner]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(organization_id=self.organization.id).order_by("-created_at")

    def _execution_team(self) -> Team:
        user = cast(User, self.request.user)
        try:
            return billing_alerts_api.execution_team_for_organization(self.organization.id, user.team)
        except billing_alerts_api.BillingAlertExecutionTeamUnavailable as e:
            raise ValidationError(str(e)) from e

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        user = cast(User, self.request.user)
        execution_team = self._execution_team()
        serializer.save(
            organization_id=self.organization.id,
            team=execution_team,
            created_by_id=user.id,
            updated_by_id=user.id,
        )
        report_user_action(user, "billing alert created", request=self.request)

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        user = cast(User, self.request.user)
        serializer.save(updated_by_id=user.id)
        report_user_action(user, "billing alert updated", request=self.request)

    def perform_destroy(self, instance: BillingAlertConfiguration) -> None:
        billing_alerts_api.delete_alert_and_destinations(instance)

    @extend_schema(
        request=None,
        responses={200: BillingAlertEventSerializer(many=True)},
        description="List evaluation and notification events for this billing alert, newest first.",
    )
    @action(detail=True, methods=["GET"], url_path="events", required_scopes=["billing:read"])
    def events(self, request: Request, *args: object, **kwargs: object) -> Response:
        alert = self.get_object()
        queryset = billing_alerts_api.visible_events_for_alert(alert)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = BillingAlertEventSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = BillingAlertEventSerializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        request=None,
        responses={200: BillingAlertCheckNowResponseSerializer},
        description=(
            "Evaluate this billing alert immediately against real billing usage or spend data. "
            "Manual checks can send notifications when the evaluation records a dispatchable event."
        ),
    )
    @action(detail=True, methods=["POST"], url_path="check_now", required_scopes=["billing:write"])
    def check_now(self, request: Request, *args: object, **kwargs: object) -> Response:
        alert = self.get_object()
        result = billing_alerts_api.evaluate_and_dispatch_alert(alert)
        response = BillingAlertCheckNowResponseSerializer(
            {"event": result.event, "dispatched_destinations": result.dispatched_destinations}
        )
        report_user_action(request.user, "billing alert checked now", {"alert_id": str(alert.id)}, request=request)
        return Response(response.data)

    @extend_schema(
        request=BillingAlertCreateDestinationSerializer,
        responses={201: BillingAlertDestinationResponseSerializer},
        description="Create a notification destination for this alert. One HogFunction is created per alert event kind.",
    )
    @action(detail=True, methods=["POST"], url_path="destinations", required_scopes=["billing:write"])
    def create_destination(self, request: Request, *args: object, **kwargs: object) -> Response:
        alert = self.get_object()
        serializer = BillingAlertCreateDestinationSerializer(data=request.data, context={"alert": alert})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        hog_function_ids = billing_alerts_api.create_destination(alert, request=self.request, data=data)

        report_user_action(
            request.user,
            "billing alert destination created",
            {"alert_id": str(alert.id), "type": data["type"], "event_kinds": list(billing_alerts_api.EVENT_KINDS)},
            request=request,
        )
        response = BillingAlertDestinationResponseSerializer({"hog_function_ids": hog_function_ids})
        return Response(response.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=BillingAlertDeleteDestinationSerializer,
        responses={204: None},
        description="Delete a notification destination by deleting its HogFunction group atomically.",
    )
    @action(detail=True, methods=["POST"], url_path="destinations/delete", required_scopes=["billing:write"])
    def delete_destination(self, request: Request, *args: object, **kwargs: object) -> Response:
        alert = self.get_object()
        serializer = BillingAlertDeleteDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hog_function_ids = serializer.validated_data["hog_function_ids"]

        try:
            billing_alerts_api.delete_destination(alert, hog_function_ids)
        except billing_alerts_api.BillingAlertDestinationOwnershipError:
            raise ValidationError("One or more HogFunctions do not belong to this alert.")

        report_user_action(
            request.user,
            "billing alert destination deleted",
            {"alert_id": str(alert.id), "count": len(hog_function_ids)},
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
