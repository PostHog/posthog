import secrets
from functools import cached_property
from typing import Any
from urllib.parse import urlsplit

from django.db import transaction
from django.db.models import Count, QuerySet
from django.views.decorators.debug import sensitive_variables

from drf_spectacular.helpers import forced_singular_serializer
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.constants import AvailableFeature
from posthog.event_usage import report_organization_action
from posthog.exceptions import Conflict, PaidFeatureException
from posthog.models.ssf import SSFConfiguration, SSFConnection, SSFStream
from posthog.permissions import OrganizationAdminWritePermissions, TimeSensitiveActionPermission
from posthog.ssf.provisioning import SSFOperationInProgress, SSFProvisioning
from posthog.ssf.remote import SSFRemoteError
from posthog.ssf.serializers import (
    SSFConfigurationSerializer,
    SSFConnectionSerializer,
    SSFCredentialSerializer,
    SSFSettingsSerializer,
    SSFStatusInputSerializer,
    SSFStreamCreateSerializer,
    SSFStreamSerializer,
    SSFStreamUpdateSerializer,
    SSFSubjectInputSerializer,
    SSFVerificationInputSerializer,
)
from posthog.ssf.service import SSFService
from posthog.ssf.validation import CONTROL_EVENTS


class SSFEntitlementPermission(permissions.BasePermission):
    def has_permission(self, request: Request, view: Any) -> bool:
        if not view.organization.is_feature_available(AvailableFeature.SSF):
            raise PaidFeatureException(AvailableFeature.SSF)
        return True


@extend_schema(extensions={"x-product": "core"})
class SSFOrganizationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "organization"
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "destroy",
        "configure",
        "rotate_key",
        "rotate_token",
        "refresh",
        "provision",
        "verify",
        "set_status",
        "add_subject",
        "remove_subject",
    ]
    permission_classes = [OrganizationAdminWritePermissions, TimeSensitiveActionPermission, SSFEntitlementPermission]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    @cached_property
    def ssf_configuration(self) -> SSFConfiguration:
        return SSFConfiguration.objects.filter(organization=self.organization).first() or SSFConfiguration(
            organization=self.organization
        )

    def ensure_configuration(self) -> SSFConfiguration:
        with transaction.atomic():
            config, _ = SSFConfiguration.objects.get_or_create(organization=self.organization)
            config = SSFConfiguration.objects.select_for_update().get(organization=self.organization, pk=config.pk)
            if not config.signing_key:
                SSFService.rotate_signing_key(config)
                config.save(update_fields=["signing_key", "signing_key_id", "previous_public_keys", "updated_at"])
        self.__dict__["ssf_configuration"] = config
        return config

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, SSFStream.DoesNotExist):
            exc = exceptions.NotFound("The stream is not available for this operation.")
        elif isinstance(exc, SSFOperationInProgress):
            exc = Conflict(str(exc))
        elif isinstance(exc, SSFRemoteError) and exc.retry_after is not None:
            exc = exceptions.Throttled(wait=exc.retry_after, detail=str(exc))
        elif isinstance(exc, ValueError):
            exc = exceptions.ValidationError(str(exc))
        return super().handle_exception(exc)


class SSFConfigurationViewSet(SSFOrganizationViewSet):
    serializer_class = SSFSettingsSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def _response(self, config: SSFConfiguration) -> Response:
        issuer = SSFService.issuer(self.organization)
        parsed = urlsplit(issuer)
        endpoints = {
            "issuer": issuer,
            "discovery_url": f"{parsed.scheme}://{parsed.netloc}/.well-known/ssf-configuration/{self.organization.id}",
            "jwks_url": f"{issuer}/jwks.json",
        }
        return Response(
            {**SSFSettingsSerializer(config).data, "endpoints": endpoints}, headers={"Cache-Control": "no-store"}
        )

    @extend_schema(responses=forced_singular_serializer(SSFSettingsSerializer))
    def list(self, request: Request, **kwargs: Any) -> Response:
        report_organization_action(self.organization, "ssf configuration viewed")
        return self._response(self.ssf_configuration)

    @extend_schema(request=SSFConfigurationSerializer, responses=SSFSettingsSerializer)
    @action(detail=False, methods=["patch"], url_path="configuration")
    def configure(self, request: Request, **kwargs: Any) -> Response:
        config = self.ensure_configuration()
        with transaction.atomic():
            config = SSFConfiguration.objects.select_for_update().get(organization=self.organization, pk=config.pk)
            serializer = SSFConfigurationSerializer(config, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
        report_organization_action(self.organization, "ssf configured", {"enabled": config.enabled})
        return self._response(config)

    @extend_schema(request=None, responses=SSFSettingsSerializer)
    @action(detail=False, methods=["post"], url_path="rotate_key")
    def rotate_key(self, request: Request, **kwargs: Any) -> Response:
        config = self.ensure_configuration()
        with transaction.atomic():
            config = SSFConfiguration.objects.select_for_update().get(organization=self.organization, pk=config.pk)
            SSFService.rotate_signing_key(config)
            config.save(update_fields=["signing_key", "signing_key_id", "previous_public_keys", "updated_at"])
        report_organization_action(self.organization, "ssf signing key rotated")
        return self._response(config)


class SSFConnectionViewSet(SSFOrganizationViewSet, viewsets.ModelViewSet):
    queryset = SSFConnection.objects.annotate(stream_count=Count("streams")).order_by("created_at", "id")
    serializer_class = SSFConnectionSerializer
    pagination_class = None

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(organization=self.organization)

    @sensitive_variables("serializer", "connection")
    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        connection = SSFConnection(organization=self.organization, **serializer.validated_data)
        if connection.direction == SSFConnection.Direction.OUTGOING and not connection.audience:
            connection.audience = str(connection.id)
        if connection.direction == SSFConnection.Direction.INCOMING:
            SSFProvisioning.refresh_connection(connection)
        config = self.ensure_configuration()
        with transaction.atomic():
            SSFConfiguration.objects.select_for_update().get(organization=self.organization, pk=config.pk)
            if SSFConnection.objects.filter(organization=self.organization).count() >= 100:
                raise Conflict(
                    "This organization has reached its 100-connection limit. Delete an unused connection and try again."
                )
            connection.save()
        serializer.instance = connection
        report_organization_action(self.organization, "ssf connection created", {"direction": connection.direction})

    @sensitive_variables("serializer")
    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        serializer.save()
        report_organization_action(self.organization, "ssf connection updated")

    def perform_destroy(self, instance: SSFConnection) -> None:
        instance.enabled = False
        instance.save(update_fields=["enabled", "updated_at"])
        for stream in (
            SSFStream.objects.filter(organization=self.organization, connection=instance)
            .select_related("connection")
            .order_by("id")
        ):
            SSFProvisioning.delete_stream(self.ssf_configuration, stream)
        instance.delete()
        report_organization_action(self.organization, "ssf connection deleted")

    @extend_schema(request=None, responses=SSFCredentialSerializer)
    @action(detail=True, methods=["post"])
    @sensitive_variables("token")
    def rotate_token(self, request: Request, **kwargs: Any) -> Response:
        connection = self.get_object()
        if connection.direction != SSFConnection.Direction.OUTGOING:
            raise exceptions.ValidationError("Incoming delivery credentials are managed automatically for each stream.")
        token = f"phssf_{secrets.token_urlsafe(32)}"
        connection.token_hash = SSFService.token_hash(token)
        connection.save(update_fields=["token_hash", "updated_at"])
        report_organization_action(self.organization, "ssf credential rotated", {"direction": "outgoing"})
        return Response({"token": token}, headers={"Cache-Control": "no-store"})

    @extend_schema(request=None, responses=SSFConnectionSerializer)
    @action(detail=True, methods=["post"])
    def refresh(self, request: Request, **kwargs: Any) -> Response:
        connection = SSFProvisioning.refresh_connection(self.get_object(), force=True)
        connection.save(update_fields=["jwks_uri", "metadata", "legacy_jwks", "discovered_at", "updated_at"])
        return Response(SSFConnectionSerializer(connection).data)


class SSFStreamViewSet(SSFOrganizationViewSet, viewsets.ModelViewSet):
    queryset = SSFStream.objects.select_related("connection").order_by("created_at", "id")
    serializer_class = SSFStreamSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(organization=self.organization, connection__organization=self.organization)

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.action == "create":
            return SSFStreamCreateSerializer
        return SSFStreamUpdateSerializer if self.action == "partial_update" else SSFStreamSerializer

    @extend_schema(request=SSFStreamCreateSerializer, responses={201: SSFStreamSerializer})
    def create(self, request: Request, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        connection = serializer.validated_data["connection"]
        config = self.ensure_configuration()
        events = serializer.validated_data.get("events_requested", CONTROL_EVENTS)
        description = serializer.validated_data["description"]
        if connection.direction == SSFConnection.Direction.OUTGOING:
            stream = SSFService.create_outgoing_stream(config, connection, events, description)
        else:
            if not SSFService.is_connection_enabled(config, connection):
                raise exceptions.ValidationError("Enable SSF and this connection before provisioning incoming streams.")
            with transaction.atomic():
                SSFConnection.objects.select_for_update().get(organization=self.organization, pk=connection.pk)
                if SSFStream.objects.filter(organization=self.organization, connection=connection).count() >= 100:
                    raise Conflict(
                        "This connection has reached its 100-stream limit. Delete an unused stream and try again."
                    )
                stream = SSFStream.objects.create(
                    organization=self.organization,
                    connection=connection,
                    audience="",
                    events_requested=events,
                    description=description,
                    status=SSFStream.Status.PROVISIONING,
                )
            stream = SSFProvisioning.provision(config, stream)
        stream.refresh_from_db()
        return Response(SSFStreamSerializer(stream).data, status=201)

    @extend_schema(request=SSFStreamUpdateSerializer, responses=SSFStreamSerializer)
    def partial_update(self, request: Request, **kwargs: Any) -> Response:
        stream = self.get_object()
        serializer = SSFStreamUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updates = serializer.validated_data
        peer = stream.connection
        if peer is None:
            raise exceptions.NotFound("The stream has no connection.")
        if all(getattr(stream, field) == value for field, value in updates.items()):
            return Response(SSFStreamSerializer(stream).data)
        if peer.direction == SSFConnection.Direction.INCOMING:
            stream = SSFProvisioning.provision(self.ssf_configuration, stream, **updates)
        else:
            stream = SSFService.update_outgoing_stream(self.ssf_configuration, stream, **updates)
        stream.refresh_from_db()
        report_organization_action(self.organization, "ssf stream updated", {"direction": peer.direction})
        return Response(SSFStreamSerializer(stream).data)

    def perform_destroy(self, instance: SSFStream) -> None:
        SSFProvisioning.delete_stream(self.ssf_configuration, instance)

    @extend_schema(request=None, responses=SSFStreamSerializer)
    @action(detail=True, methods=["post"])
    def provision(self, request: Request, **kwargs: Any) -> Response:
        stream = SSFProvisioning.provision(self.ssf_configuration, self.get_object())
        stream.refresh_from_db()
        return Response(SSFStreamSerializer(stream).data)

    @extend_schema(request=SSFVerificationInputSerializer, responses=SSFStreamSerializer)
    @action(detail=True, methods=["post"])
    def verify(self, request: Request, **kwargs: Any) -> Response:
        stream = self.get_object()
        serializer = SSFVerificationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if stream.connection.direction == SSFConnection.Direction.INCOMING:
            SSFProvisioning.verify(self.ssf_configuration, stream, serializer.validated_data.get("state"))
        else:
            SSFService.request_verification(self.ssf_configuration, stream, serializer.validated_data.get("state"))
        stream.refresh_from_db()
        return Response(SSFStreamSerializer(stream).data)

    @extend_schema(request=SSFStatusInputSerializer, responses=SSFStreamSerializer)
    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request: Request, **kwargs: Any) -> Response:
        stream = self.get_object()
        serializer = SSFStatusInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if stream.connection.direction == SSFConnection.Direction.INCOMING:
            stream = SSFProvisioning.set_status(self.ssf_configuration, stream, data["status"], data["reason"])
        else:
            stream = SSFService.set_status_from_receiver(self.ssf_configuration, stream, data["status"], data["reason"])
        return Response(SSFStreamSerializer(stream).data)

    def _subject(self, request: Request, *, remove: bool) -> Response:
        stream = self.get_object()
        serializer = SSFSubjectInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        subject = serializer.validated_data["subject"]
        if stream.connection.direction == SSFConnection.Direction.INCOMING:
            SSFProvisioning.subject(self.ssf_configuration, stream, subject, remove=remove)
        else:
            SSFService.update_subject(self.ssf_configuration, stream, subject, remove=remove)
        return Response(status=204)

    @extend_schema(request=SSFSubjectInputSerializer, responses={204: None})
    @action(detail=True, methods=["post"])
    def add_subject(self, request: Request, **kwargs: Any) -> Response:
        return self._subject(request, remove=False)

    @extend_schema(request=SSFSubjectInputSerializer, responses={204: None})
    @action(detail=True, methods=["post"])
    def remove_subject(self, request: Request, **kwargs: Any) -> Response:
        return self._subject(request, remove=True)
