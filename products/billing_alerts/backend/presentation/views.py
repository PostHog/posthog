from __future__ import annotations

from typing import cast

from django.db import transaction
from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.team.team import Team
from posthog.models.user import User

from products.billing_alerts.backend.alert_destinations import EVENT_KINDS, EventKind, build_destination_config
from products.billing_alerts.backend.logic.notifications import dispatch_billing_alert_event
from products.billing_alerts.backend.logic.state_machine import evaluate_and_record_billing_alert, event_should_dispatch
from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvent
from products.billing_alerts.backend.presentation.permissions import IsOrganizationAdminOrOwner
from products.billing_alerts.backend.presentation.serializers import (
    BillingAlertCheckNowResponseSerializer,
    BillingAlertConfigurationSerializer,
    BillingAlertCreateDestinationSerializer,
    BillingAlertDeleteDestinationSerializer,
    BillingAlertDestinationResponseSerializer,
    BillingAlertEventSerializer,
    visible_billing_alert_events,
)
from products.cdp.backend.api.hog_function import HogFunctionSerializer
from products.cdp.backend.models.hog_functions.hog_function import HogFunction


@extend_schema(tags=["billing"], extensions={"x-product": "core"})
class BillingAlertViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = BillingAlertConfiguration.objects.all()
    serializer_class = BillingAlertConfigurationSerializer
    lookup_field = "id"
    permission_classes = [IsOrganizationAdminOrOwner]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(organization_id=self.organization.id).order_by("-created_at")

    def _execution_team(self) -> Team:
        user = cast(User, self.request.user)
        if user.team and user.team.organization_id == self.organization.id:
            return user.team
        team = Team.objects.filter(organization_id=self.organization.id).order_by("id").first()
        if team is None:
            raise ValidationError("This organization does not have an execution team.")
        return team

    def perform_create(self, serializer: BillingAlertConfigurationSerializer) -> None:
        user = cast(User, self.request.user)
        execution_team = self._execution_team()
        serializer.save(
            organization_id=self.organization.id,
            execution_team_id=execution_team.id,
            created_by_id=user.id,
            updated_by_id=user.id,
        )
        report_user_action(user, "billing alert created", request=self.request)

    def perform_update(self, serializer: BillingAlertConfigurationSerializer) -> None:
        user = cast(User, self.request.user)
        serializer.save(updated_by_id=user.id)
        report_user_action(user, "billing alert updated", request=self.request)

    @extend_schema(
        request=None,
        responses={200: BillingAlertEventSerializer(many=True)},
        description="List evaluation and notification events for this billing alert, newest first.",
    )
    @action(detail=True, methods=["GET"], url_path="events", required_scopes=["billing:read"])
    def events(self, request: Request, *args: object, **kwargs: object) -> Response:
        alert = self.get_object()
        queryset = visible_billing_alert_events(BillingAlertEvent.objects.filter(alert=alert))
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = BillingAlertEventSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = BillingAlertEventSerializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        request=None,
        responses={200: BillingAlertCheckNowResponseSerializer},
        description="Evaluate this billing alert immediately against real billing usage or spend data.",
    )
    @action(detail=True, methods=["POST"], url_path="check_now", required_scopes=["billing:write"])
    def check_now(self, request: Request, *args: object, **kwargs: object) -> Response:
        alert = self.get_object()
        event = evaluate_and_record_billing_alert(alert)
        dispatched = dispatch_billing_alert_event(event) if event_should_dispatch(event) else 0
        response = BillingAlertCheckNowResponseSerializer({"event": event, "dispatched_destinations": dispatched})
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
        serializer = BillingAlertCreateDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            team = Team.objects.get(id=alert.execution_team_id)
            hog_functions = [self._build_and_create_hog_function(alert, team, data, kind) for kind in EVENT_KINDS]

        report_user_action(
            request.user,
            "billing alert destination created",
            {"alert_id": str(alert.id), "type": data["type"], "event_kinds": list(EVENT_KINDS)},
            request=request,
        )
        response = BillingAlertDestinationResponseSerializer({"hog_function_ids": [hf.id for hf in hog_functions]})
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

        with transaction.atomic():
            updated = HogFunction.objects.filter(
                team_id=alert.execution_team_id,
                id__in=hog_function_ids,
                filters__properties__contains=[{"key": "alert_id", "value": str(alert.id)}],
            ).update(deleted=True)
            if updated != len(hog_function_ids):
                raise ValidationError("One or more HogFunctions do not belong to this alert.")

        report_user_action(
            request.user,
            "billing alert destination deleted",
            {"alert_id": str(alert.id), "count": len(hog_function_ids)},
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _build_and_create_hog_function(
        self,
        alert: BillingAlertConfiguration,
        team: Team,
        data: dict,
        kind: EventKind,
    ) -> HogFunction:
        config = build_destination_config(alert, team, kind, data)
        team = config.pop("team")
        serializer = HogFunctionSerializer(
            data=config,
            context={"request": self.request, "get_team": lambda: team, "is_create": True},
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save(team=team)
