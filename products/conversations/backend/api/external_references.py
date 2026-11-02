import logging
from uuid import UUID

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field, extend_schema_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.integration import github_rate_limited_response
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.integration import is_supported_external_issue_provider
from posthog.permissions import APIScopePermission

from products.conversations.backend.logic.external_references import (
    TicketExternalReferenceValidationError,
    create_external_reference,
    delete_external_reference,
    get_external_reference,
    list_external_references,
    search_external_issues,
)
from products.conversations.backend.models import TicketExternalReference

logger = logging.getLogger(__name__)


@extend_schema_serializer(component_name="TicketExternalReferenceIntegrationResult")
class TicketExternalReferenceIntegrationSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True, help_text="ID of the integration backing this external reference.")
    kind = serializers.CharField(
        read_only=True, help_text="Integration provider, e.g. 'github', 'gitlab', 'linear', or 'jira'."
    )
    display_name = serializers.CharField(read_only=True, help_text="Human-readable name of the connected integration.")


@extend_schema_field({"type": "object", "additionalProperties": {"type": "string"}})
class ExternalReferenceConfigField(serializers.JSONField):
    pass


@extend_schema_field({"type": "object", "additionalProperties": True})
class ExternalReferenceContextField(serializers.JSONField):
    pass


@extend_schema_serializer(component_name="TicketExternalReferenceResult")
class TicketExternalReferenceResultSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique ID of the external reference.")
    ticket_id = serializers.UUIDField(read_only=True, help_text="ID of the ticket this reference is linked to.")
    integration = TicketExternalReferenceIntegrationSerializer(
        read_only=True, help_text="The connected integration this reference was created through."
    )
    external_url = serializers.SerializerMethodField(
        help_text="URL of the linked external issue in the provider's system."
    )
    external_id = serializers.CharField(read_only=True, help_text="Provider-native identifier of the linked issue.")
    title = serializers.CharField(read_only=True, help_text="Title of the linked issue.")
    created_at = serializers.DateTimeField(read_only=True)

    @extend_schema_field(serializers.CharField())
    def get_external_url(self, reference: TicketExternalReference) -> str:
        if reference.external_url:
            return reference.external_url

        if is_supported_external_issue_provider(reference.integration.kind):
            raise ValidationError("Missing required external context fields")

        raise ValidationError("Provider not supported")


@extend_schema_serializer(component_name="TicketExternalReferenceCreate")
class TicketExternalReferenceCreateSerializer(TicketExternalReferenceResultSerializer):
    integration_id = serializers.IntegerField(
        write_only=True,
        help_text="ID of the connected integration to create the external issue with.",
    )
    config = ExternalReferenceConfigField(
        write_only=True,
        help_text="Provider-specific fields describing the external issue to create.",
    )
    ticket = serializers.UUIDField(write_only=True, help_text="ID of the support ticket to link the reference to.")


@extend_schema_serializer(component_name="TicketExternalReferenceLink")
class TicketExternalReferenceLinkSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(
        write_only=True,
        help_text="ID of the connected integration the existing issue lives in.",
    )
    ticket = serializers.UUIDField(write_only=True, help_text="ID of the support ticket to link the reference to.")
    external_context = ExternalReferenceContextField(
        write_only=True,
        help_text="Identifier and optional title of the existing external issue to link.",
    )


class TicketExternalIssueSearchQuerySerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(
        help_text="ID of the connected integration to search issues in.",
    )
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Text to match against existing issue titles or identifiers in the provider.",
    )
    repository = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Repository to search within. Required for GitHub, ignored by other providers.",
    )


@extend_schema_serializer(component_name="TicketExternalIssueResult")
class TicketExternalIssueResultSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Provider-native identifier of the issue (e.g. issue key or number).")
    title = serializers.CharField(help_text="Human-readable issue title, for display in the picker.")
    url = serializers.CharField(help_text="Link to the issue in the provider's system.")
    external_context = ExternalReferenceContextField(
        help_text="Payload to send back as external_context when linking this issue.",
    )


@extend_schema_serializer(component_name="TicketExternalIssueSearchResult")
class TicketExternalIssueSearchResponseSerializer(serializers.Serializer):
    issues = TicketExternalIssueResultSerializer(many=True, help_text="Matching existing issues.")


class TicketExternalReferenceViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "ticket"
    scope_object_read_actions = ["list", "retrieve", "search_issues"]
    scope_object_write_actions = ["create", "link_issue", "destroy"]
    serializer_class = TicketExternalReferenceResultSerializer
    permission_classes = [IsAuthenticated, APIScopePermission]

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, GitHubRateLimitError):
            return github_rate_limited_response(exc)
        return super().handle_exception(exc)

    def list(self, request: Request, *args, **kwargs) -> Response:
        ticket_id = request.query_params.get("ticket_id")
        parsed_ticket_id = None
        if ticket_id:
            try:
                parsed_ticket_id = UUID(str(ticket_id))
            except ValueError:
                raise ValidationError("Invalid ticket_id")

        references = list_external_references(team_id=self.team.id, ticket_id=parsed_ticket_id)

        page = self.paginate_queryset(references)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(references, many=True)
        return Response(serializer.data)

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        try:
            reference_id = UUID(str(kwargs["pk"]))
        except ValueError as error:
            raise ValidationError("Invalid external reference id") from error

        reference = get_external_reference(reference_id=reference_id, team_id=self.team.id)
        if reference is None:
            raise NotFound("External reference not found")

        serializer = self.get_serializer(reference)
        return Response(serializer.data)

    @extend_schema(
        request=TicketExternalReferenceCreateSerializer,
        responses={201: TicketExternalReferenceResultSerializer},
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = TicketExternalReferenceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticket_id = serializer.validated_data["ticket"]
        if not isinstance(ticket_id, UUID):
            ticket_id = UUID(str(ticket_id))

        try:
            reference, _ = create_external_reference(
                team_id=self.team.id,
                ticket_id=ticket_id,
                integration_id=serializer.validated_data["integration_id"],
                config=serializer.validated_data["config"],
                created_by=request.user,
            )
        except TicketExternalReferenceValidationError as error:
            logger.warning("Failed to create external reference for ticket", exc_info=error)
            raise ValidationError(str(error)) from error

        response_serializer = self.get_serializer(reference)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=TicketExternalReferenceLinkSerializer,
        responses={201: TicketExternalReferenceResultSerializer},
    )
    @action(methods=["POST"], detail=False, url_path="link_issue")
    def link_issue(self, request: Request, *args, **kwargs) -> Response:
        serializer = TicketExternalReferenceLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticket_id = serializer.validated_data["ticket"]
        if not isinstance(ticket_id, UUID):
            ticket_id = UUID(str(ticket_id))

        try:
            reference, _ = create_external_reference(
                team_id=self.team.id,
                ticket_id=ticket_id,
                integration_id=serializer.validated_data["integration_id"],
                external_context=serializer.validated_data["external_context"],
                created_by=request.user,
            )
        except TicketExternalReferenceValidationError as error:
            logger.warning("Failed to link external reference for ticket", exc_info=error)
            raise ValidationError(str(error)) from error

        response_serializer = self.get_serializer(reference)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        try:
            reference_id = UUID(str(kwargs["pk"]))
        except ValueError as error:
            raise ValidationError("Invalid external reference id") from error

        success = delete_external_reference(team_id=self.team.id, reference_id=reference_id)
        if not success:
            raise NotFound("External reference not found")

        return Response(status=status.HTTP_204_NO_CONTENT)

    @validated_request(
        query_serializer=TicketExternalIssueSearchQuerySerializer,
        responses={200: OpenApiResponse(response=TicketExternalIssueSearchResponseSerializer)},
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="search_issues",
        pagination_class=None,
        required_scopes=["ticket:read", "integration:read"],
    )
    def search_issues(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        try:
            issues = search_external_issues(
                team_id=self.team.id,
                integration_id=request.validated_query_data["integration_id"],
                search=request.validated_query_data["search"],
                repository=request.validated_query_data.get("repository") or None,
            )
        except TicketExternalReferenceValidationError as error:
            raise ValidationError(str(error)) from error

        response_serializer = TicketExternalIssueSearchResponseSerializer({"issues": issues})
        return Response(response_serializer.data)
