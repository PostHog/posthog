from typing import Any, cast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema, extend_schema_field, extend_schema_view
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from posthog.schema import HogQLVariable

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.data_deletion import (
    DataDeletionActiveRequestLimit,
    DataDeletionSubmissionConflict,
    create_event_deletion_request,
    preview_event_deletion,
    validate_payload_size,
)
from posthog.models import Team, User
from posthog.models.data_deletion_request import DataDeletionRequest, RequestType
from posthog.permissions import posthog_feature_flag_enabled
from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle

SELF_SERVICE_DATA_DELETION_FLAG = "self-service-data-deletion"


class DataDeletionTeamRateThrottle(PersonalApiKeyOrUserRateThrottle):
    def get_cache_key(self, request: Request, view: APIView) -> str:
        team_id = self.safely_get_team_id_from_view(view)
        ident = team_id if team_id is not None else request.user.pk
        return self.cache_format % {"scope": self.scope, "ident": ident}


class DataDeletionCreateThrottle(DataDeletionTeamRateThrottle):
    scope = "data_deletion_create"
    rate = "10/hour"


class DataDeletionPreviewBurstThrottle(DataDeletionTeamRateThrottle):
    scope = "data_deletion_preview_burst"
    rate = "5/minute"


class DataDeletionPreviewSustainedThrottle(DataDeletionTeamRateThrottle):
    scope = "data_deletion_preview_sustained"
    rate = "30/hour"


@extend_schema_field(
    {
        "type": "object",
        "additionalProperties": HogQLVariable.model_json_schema(),
    }
)
class HogQLVariablesField(serializers.JSONField):
    pass


class DataDeletionRequestInputSerializer(serializers.Serializer):
    query = serializers.CharField(help_text="HogQL query that selects one event UUID column.")
    variables = HogQLVariablesField(
        default=dict,
        help_text="Variables referenced by the HogQL query.",
    )

    def validate_variables(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise ValidationError("Query variables must be a JSON object.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        try:
            validate_payload_size(attrs["query"], attrs["variables"])
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict) from error
        return attrs


class DataDeletionRequestCreateSerializer(DataDeletionRequestInputSerializer):
    submission_id = serializers.UUIDField(
        required=True,
        help_text="Client-generated identifier that makes request submission idempotent.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        unexpected = set(self.initial_data) - set(self.fields)
        if unexpected:
            raise serializers.ValidationError(dict.fromkeys(unexpected, "This field is not accepted."))
        return attrs


class DataDeletionPreviewSerializer(serializers.Serializer):
    count = serializers.IntegerField(
        read_only=True,
        help_text="Number of event UUIDs selected when the preview ran.",
    )


class DataDeletionConflictSerializer(serializers.Serializer):
    detail = serializers.CharField(
        read_only=True,
        help_text="Reason the deletion request could not be created in the current state.",
    )


class DataDeletionRequestSerializer(serializers.ModelSerializer):
    query = serializers.CharField(source="hogql_query", read_only=True, help_text="Submitted HogQL query snapshot.")
    variables = HogQLVariablesField(
        source="hogql_variables",
        read_only=True,
        help_text="Submitted HogQL variable snapshot.",
    )
    created_by_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="Identifier of the user who submitted the request.",
    )

    class Meta:
        model = DataDeletionRequest
        fields = [
            "id",
            "status",
            "query",
            "variables",
            "submission_id",
            "count",
            "created_by_id",
            "created_by_staff",
            "created_at",
            "updated_at",
            "approved_at",
            "stats_calculated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Deletion request identifier."},
            "status": {"help_text": "Current deletion workflow status."},
            "submission_id": {"help_text": "Client-generated idempotency identifier."},
            "count": {"help_text": "Number of selected events, when calculated."},
            "created_by_staff": {"help_text": "Whether the submitter was a PostHog staff user."},
            "created_at": {"help_text": "Time when the request was submitted."},
            "updated_at": {"help_text": "Time when the request last changed."},
            "approved_at": {"help_text": "Time when the request was approved, if approved."},
            "stats_calculated_at": {"help_text": "Time when selection statistics were calculated, if available."},
        }


@extend_schema_view(
    list=extend_schema(description="List self-service event deletion requests for this project."),
    retrieve=extend_schema(description="Get one self-service event deletion request for this project."),
)
@extend_schema(extensions={"x-product": "core"})
class DataDeletionRequestViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "data_deletion"
    requires_resource_level_access = True
    queryset = DataDeletionRequest.objects.all()
    serializer_class = DataDeletionRequestSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action == "create":
            return [DataDeletionCreateThrottle()]
        return super().get_throttles()

    def initial(self, request: Request, *args: object, **kwargs: object) -> None:
        super().initial(request, *args, **kwargs)
        if not self_service_data_deletion_enabled(self.team):
            raise PermissionDenied("Self-service data deletion is not enabled for this project.")

    def safely_get_queryset(self, queryset: QuerySet[DataDeletionRequest]) -> QuerySet[DataDeletionRequest]:
        return queryset.filter(request_type=RequestType.HOGQL_EVENT_REMOVAL)

    @validated_request(
        request_serializer=DataDeletionRequestCreateSerializer,
        responses={
            200: DataDeletionRequestSerializer,
            201: DataDeletionRequestSerializer,
            409: DataDeletionConflictSerializer,
        },
        description="Submit a one-column HogQL query for event deletion.",
    )
    def create(self, request: ValidatedRequest, *args: object, **kwargs: object) -> Response:
        data = request.validated_data
        try:
            deletion_request, created = create_event_deletion_request(
                query=data["query"],
                variables=data["variables"],
                submission_id=data["submission_id"],
                team=self.team,
                user=cast(User, request.user),
            )
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict) from error
        except DataDeletionSubmissionConflict:
            return Response(
                {"detail": "This submission ID is already used by a different deletion request."},
                status=status.HTTP_409_CONFLICT,
            )
        except DataDeletionActiveRequestLimit:
            return Response(
                {"detail": "This project already has the maximum number of active deletion requests."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            DataDeletionRequestSerializer(deletion_request).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @validated_request(
        request_serializer=DataDeletionRequestInputSerializer,
        description="Validate a one-column HogQL query and count the selected event UUIDs.",
        responses={200: DataDeletionPreviewSerializer},
    )
    @action(
        methods=["POST"],
        detail=False,
        throttle_classes=[DataDeletionPreviewBurstThrottle, DataDeletionPreviewSustainedThrottle],
    )
    def preview(self, request: ValidatedRequest, **kwargs: object) -> Response:
        data = request.validated_data
        try:
            count = preview_event_deletion(
                query=data["query"],
                variables=data["variables"],
                team=self.team,
                user=cast(User, request.user),
            )
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict) from error
        return Response(DataDeletionPreviewSerializer({"count": count}).data)


def self_service_data_deletion_enabled(team: Team) -> bool:
    try:
        return posthog_feature_flag_enabled(
            SELF_SERVICE_DATA_DELETION_FLAG,
            str(team.uuid),
            organization_id=team.organization_id,
            team_id=team.id,
            only_evaluate_locally=True,
        )
    except Exception:
        return False
