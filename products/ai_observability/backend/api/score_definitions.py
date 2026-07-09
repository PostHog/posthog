from __future__ import annotations

from typing import Any, cast

from django.db import transaction
from django.db.models import Q, QuerySet

import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import extend_schema
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import AccessControlPermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from products.ai_observability.backend.models.score_definitions import ScoreDefinition, StaleScoreDefinitionVersion
from products.ai_observability.backend.score_definition_configs import ScoreDefinitionConfigField


class ScoreDefinitionSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="User who created the scorer.",
    )
    current_version = serializers.IntegerField(
        source="current_version.version",
        read_only=True,
        help_text="Current immutable configuration version number.",
    )
    current_version_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="UUID of the current version row. Matches `system.score_definitions.current_version_id` in HogQL.",
    )
    config = ScoreDefinitionConfigField(
        source="current_version.config",
        read_only=True,
        help_text="Current immutable scorer configuration.",
    )

    class Meta:
        model = ScoreDefinition
        fields = [
            "id",
            "name",
            "description",
            "kind",
            "archived",
            "current_version",
            "current_version_id",
            "config",
            "created_by",
            "created_at",
            "updated_at",
            "team",
        ]
        read_only_fields = fields


class ScoreDefinitionCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="Human-readable scorer name.")
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Optional human-readable description.",
    )
    kind = serializers.ChoiceField(
        choices=ScoreDefinition.Kind.choices,
        help_text="Scorer kind. This cannot be changed after creation.",
    )
    archived = serializers.BooleanField(
        required=False,
        default=False,
        help_text="New scorers are always created as active.",
    )
    config = ScoreDefinitionConfigField(help_text="Initial immutable scorer configuration.")

    def validate_name(self, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise serializers.ValidationError("`name` is required.")
        return normalized_value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("archived"):
            raise serializers.ValidationError({"archived": "New scorers must be created as active."})
        return attrs


class ScoreDefinitionMetadataSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False, help_text="Updated scorer name.")
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Updated scorer description.",
    )
    archived = serializers.BooleanField(
        required=False,
        help_text="Whether the scorer is archived.",
    )

    def validate_name(self, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise serializers.ValidationError("`name` cannot be blank.")
        return normalized_value


class ScoreDefinitionNewVersionSerializer(serializers.Serializer):
    config = ScoreDefinitionConfigField(help_text="Next immutable scorer configuration.")
    base_version = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text=(
            "Version number the caller observed before requesting this bump. "
            "If provided and it does not match the scorer's current version, the request fails with 409. "
            "Omit to skip the optimistic-concurrency check."
        ),
    )


class ScoreDefinitionFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(
        method="filter_search",
        help_text="Search scorers by name or description.",
    )
    kind = django_filters.ChoiceFilter(
        field_name="kind",
        choices=ScoreDefinition.Kind.choices,
        help_text="Filter by scorer kind.",
    )
    archived = django_filters.BooleanFilter(
        field_name="archived",
        help_text="Filter by archived state.",
    )
    order_by = django_filters.OrderingFilter(
        fields=(
            ("name", "name"),
            ("kind", "kind"),
            ("created_at", "created_at"),
            ("updated_at", "updated_at"),
            ("current_version__version", "current_version"),
        ),
        help_text="Sort scorers by name, kind, created_at, updated_at, or current_version.",
    )

    class Meta:
        model = ScoreDefinition
        fields = ["kind", "archived"]

    def filter_search(self, queryset: QuerySet, _name: str, value: str) -> QuerySet:
        if value:
            return queryset.filter(Q(name__icontains=value) | Q(description__icontains=value))
        return queryset


class ScoreDefinitionViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "llm_analytics"
    permission_classes = [AccessControlPermission]
    serializer_class = ScoreDefinitionSerializer
    queryset = ScoreDefinition.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = ScoreDefinitionFilter
    http_method_names = ["get", "post", "patch", "head", "options"]

    def safely_get_queryset(
        self, queryset: QuerySet[ScoreDefinition, ScoreDefinition]
    ) -> QuerySet[ScoreDefinition, ScoreDefinition]:
        queryset = (
            queryset.filter(team_id=self.team_id).select_related("current_version", "created_by").order_by("name", "id")
        )

        # List defaults to active scorers to mirror the UI; non-boolean `?archived=` values keep that default.
        if self.action == "list":
            archived_param = (self.request.query_params.get("archived") or "").strip().lower()
            if archived_param not in {"true", "false", "1", "0"}:
                queryset = queryset.filter(archived=False)

        return queryset

    @staticmethod
    def _event_properties(definition: ScoreDefinition) -> dict[str, str | bool | int]:
        current_version = definition.current_version.version if definition.current_version else 0

        return {
            "scorer_id": str(definition.id),
            "scorer_name": definition.name,
            "scorer_kind": definition.kind,
            "has_description": bool(definition.description),
            "archived": definition.archived,
            "version": current_version,
        }

    @transaction.atomic
    def _create_definition(self, validated_data: dict[str, Any]) -> ScoreDefinition:
        definition_data = dict(validated_data)
        config = definition_data.pop("config")
        definition_data.pop("archived", None)
        definition_data["description"] = definition_data.get("description") or ""

        definition = ScoreDefinition.objects.create(
            team=self.team,
            created_by=cast(User, self.request.user),
            **definition_data,
        )
        definition.create_new_version(config=config, created_by=cast(User, self.request.user))
        return definition

    def _update_definition_metadata(self, definition: ScoreDefinition, validated_data: dict[str, Any]) -> list[str]:
        definition_data = dict(validated_data)
        changed_fields: list[str] = []

        if "description" in definition_data:
            definition_data["description"] = definition_data["description"] or ""

        for field, value in definition_data.items():
            if getattr(definition, field) != value:
                setattr(definition, field, value)
                changed_fields.append(field)

        if changed_fields:
            definition.save(update_fields=[*changed_fields, "updated_at"])

        return changed_fields

    def _create_definition_version(
        self, definition: ScoreDefinition, validated_data: dict[str, Any]
    ) -> ScoreDefinition:
        definition.create_new_version(
            config=validated_data["config"],
            created_by=cast(User, self.request.user),
            base_version=validated_data.get("base_version"),
        )
        definition.refresh_from_db(fields=["current_version", "updated_at"])
        return definition

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                description="Search scorers by name or description.",
                examples=[OpenApiExample("Search scorer", value="quality")],
            ),
            OpenApiParameter(
                "kind",
                OpenApiTypes.STR,
                description="Filter by scorer kind.",
                examples=[OpenApiExample("Categorical scorer", value="categorical")],
            ),
            OpenApiParameter(
                "archived",
                OpenApiTypes.BOOL,
                description="Filter by archived state.",
                examples=[OpenApiExample("Active scorers", value=False)],
            ),
            OpenApiParameter(
                "order_by",
                OpenApiTypes.STR,
                description="Sort by name, kind, created_at, updated_at, or current_version.",
                examples=[OpenApiExample("Sort by name", value="name")],
            ),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @validated_request(
        request_serializer=ScoreDefinitionCreateSerializer,
        responses={201: OpenApiResponse(response=ScoreDefinitionSerializer)},
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        definition = self._create_definition(dict(request.validated_data))

        report_user_action(
            request.user,
            "llma scorer created",
            self._event_properties(definition),
            team=self.team,
            request=request,
        )

        return Response(self.get_serializer(definition).data, status=status.HTTP_201_CREATED)

    @validated_request(
        request_serializer=ScoreDefinitionMetadataSerializer,
        responses={200: OpenApiResponse(response=ScoreDefinitionSerializer)},
    )
    def partial_update(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        definition = self.get_object()
        changed_fields = self._update_definition_metadata(definition, dict(request.validated_data))

        if changed_fields:
            event_properties: dict[str, Any] = {
                **self._event_properties(definition),
                "changed_fields": changed_fields,
            }

            if "archived" in changed_fields:
                event_properties["archived_new_value"] = definition.archived

            report_user_action(
                request.user,
                "llma scorer updated",
                event_properties,
                team=self.team,
                request=request,
            )

        return Response(self.get_serializer(definition).data, status=status.HTTP_200_OK)

    @extend_schema(request=ScoreDefinitionNewVersionSerializer, responses=ScoreDefinitionSerializer)
    @action(
        detail=True,
        methods=["post"],
        url_path="new_version",
        required_scopes=["llm_analytics:write"],
    )
    def new_version(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        definition = self.get_object()
        serializer = ScoreDefinitionNewVersionSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "score_definition_kind": definition.kind},
        )
        serializer.is_valid(raise_exception=True)

        try:
            definition = self._create_definition_version(definition, dict(serializer.validated_data))
        except StaleScoreDefinitionVersion as err:
            return Response(
                {
                    "detail": "The scorer changed since you opened it. Reload the latest version and try again.",
                    "current_version": err.current_version,
                },
                status=status.HTTP_409_CONFLICT,
            )

        report_user_action(
            request.user,
            "llma scorer version created",
            self._event_properties(definition),
            team=self.team,
            request=request,
        )

        return Response(self.get_serializer(definition).data, status=status.HTTP_200_OK)
