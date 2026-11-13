from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from django.db import transaction
from django.db.models import Count, F, Prefetch, Q, QuerySet, prefetch_related_objects

import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import extend_schema
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.pagination import PageLinksSerializer, page_link
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.models.integer_field_bounds import INTEGER_FIELD_MAX
from posthog.permissions import AccessControlPermission

from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin
from products.ai_observability.backend.api.query import EmptyQuerySerializer, StrictQuerySerializer
from products.ai_observability.backend.api.resource_tags import (
    ResourceTagFilterSerializer,
    ResourceTagsReadSerializer,
    ResourceTagsWriteSerializer,
)
from products.ai_observability.backend.composite_scorers import CompositeConfigSerializer, CompositeScorers
from products.ai_observability.backend.models.score_definitions import (
    ScoreDefinition,
    ScoreDefinitionInput,
    ScoreDefinitionVersion,
    StaleScoreDefinitionVersion,
)
from products.ai_observability.backend.read_pagination import CursorPage, cursor_page, decode_cursor, encode_cursor
from products.ai_observability.backend.resource_tags import ResourceTags
from products.ai_observability.backend.score_definition_configs import ScoreDefinitionConfigField


class CompositeInputReadSerializer(serializers.Serializer):
    alias = serializers.CharField(help_text="Input name in the formula.")
    scorer_version_id = serializers.UUIDField(source="input_version_id", help_text="Pinned immutable input version.")
    definition_id = serializers.UUIDField(source="input_version.definition_id", help_text="Input scorer definition.")
    name = serializers.CharField(source="input_version.definition.name", help_text="Input scorer name.")
    kind = serializers.ChoiceField(
        source="input_version.definition.kind", choices=ScoreDefinition.Kind.choices, help_text="Input value kind."
    )
    version = serializers.IntegerField(source="input_version.version", help_text="Pinned input version number.")
    config = ScoreDefinitionConfigField(
        source="input_version.config", read_only=True, help_text="Scoring rules of the pinned input version."
    )
    latest_version_id = serializers.UUIDField(
        source="input_version.definition.current_version_id",
        allow_null=True,
        help_text="Current input version. Updating requires a new composite version.",
    )
    latest_version = serializers.IntegerField(
        source="input_version.definition.current_version.version",
        allow_null=True,
        help_text="Current input version number.",
    )


class ScoreDefinitionSerializer(ResourceTagsReadSerializer, serializers.ModelSerializer):
    input_scorers = CompositeInputReadSerializer(
        source="current_version.inputs",
        many=True,
        read_only=True,
        help_text="Pinned inputs and their latest versions. Empty for reported scorers.",
    )
    dependent_composite_count = serializers.IntegerField(
        read_only=True,
        default=0,
        help_text="Accessible active composite scorers whose current version depends on a version of this scorer.",
    )
    calculation = serializers.ChoiceField(
        choices=ScoreDefinition.Calculation.choices,
        read_only=True,
        help_text="Whether results are reported by the caller or calculated from other item scores.",
    )
    composition = CompositeConfigSerializer(
        source="current_version.composition",
        read_only=True,
        allow_null=True,
        help_text="Formula and exact input versions for a composite scorer.",
    )
    short_name = serializers.CharField(
        read_only=True, allow_blank=True, help_text="Optional compact label for table headers and other compact views."
    )
    updated_by = UserBasicSerializer(
        read_only=True, allow_null=True, help_text="User who last updated the scorer or created a version."
    )
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
            "short_name",
            "description",
            "tags",
            "kind",
            "calculation",
            "composition",
            "input_scorers",
            "dependent_composite_count",
            "archived",
            "current_version",
            "current_version_id",
            "config",
            "created_by",
            "created_at",
            "updated_at",
            "updated_by",
            "team",
        ]
        read_only_fields = fields


class ScoreDefinitionVersionSerializer(serializers.ModelSerializer):
    calculation = serializers.ChoiceField(
        source="definition.calculation",
        choices=ScoreDefinition.Calculation.choices,
        read_only=True,
        help_text="How this scorer's results are produced.",
    )
    composition = CompositeConfigSerializer(
        read_only=True, allow_null=True, help_text="Immutable formula and input versions, or null for reported scores."
    )
    id = serializers.UUIDField(read_only=True, help_text="UUID identifying this exact immutable version.")
    definition_id = serializers.UUIDField(read_only=True, help_text="Scorer definition that owns this version.")
    version = serializers.IntegerField(read_only=True, help_text="Immutable version number within this scorer.")
    kind = serializers.ChoiceField(
        source="definition.kind", choices=ScoreDefinition.Kind.choices, read_only=True, help_text="Scorer value kind."
    )
    config = ScoreDefinitionConfigField(read_only=True, help_text="Immutable configuration for this exact version.")
    created_at = serializers.DateTimeField(read_only=True, help_text="Time this version was created.")
    created_by = UserBasicSerializer(read_only=True, allow_null=True, help_text="User who created this version.")

    class Meta:
        model = ScoreDefinitionVersion
        fields = [
            "id",
            "definition_id",
            "version",
            "kind",
            "calculation",
            "composition",
            "config",
            "created_at",
            "created_by",
        ]
        read_only_fields = fields


@extend_schema_serializer(many=False)
class ScoreDefinitionVersionPageSerializer(PageLinksSerializer):
    count = serializers.IntegerField(help_text="Total immutable versions for this scorer.")
    next_cursor = serializers.CharField(allow_null=True, help_text="Continuation cursor, or null on the last page.")
    results = ScoreDefinitionVersionSerializer(many=True, help_text="Versions on this page, newest first.")


class ScoreDefinitionVersionQuerySerializer(StrictQuerySerializer):
    limit = serializers.IntegerField(default=50, min_value=1, max_value=100, help_text="Maximum versions to return.")
    cursor = serializers.CharField(
        required=False, max_length=2048, help_text="Continuation cursor from the prior page."
    )

    def validate_cursor(self, value: str) -> tuple[int, UUID]:
        try:
            version, version_id = decode_cursor(value, 2)
            number = int(version)
            if not 1 <= number <= INTEGER_FIELD_MAX:
                raise ValueError
            return number, UUID(version_id)
        except ValueError as error:
            raise serializers.ValidationError("Provide a valid continuation cursor.") from error


def _score_definition_version_page(
    definition: ScoreDefinition,
    *,
    limit: int,
    cursor: tuple[int, UUID] | None = None,
    allowed_versions: QuerySet[ScoreDefinitionVersion] | None = None,
) -> CursorPage[ScoreDefinitionVersion]:
    versions = definition.versions.select_related("definition", "created_by").order_by("-version", "id")
    if allowed_versions is not None:
        versions = versions.filter(id__in=allowed_versions)
    count = versions.count()
    if cursor is not None:
        number, version_id = cursor
        versions = versions.filter(Q(version__lt=number) | Q(version=number, id__gt=version_id))
    rows = list(versions[: limit + 1])
    return cursor_page(
        rows,
        count=count,
        limit=limit,
        cursor_for=lambda version: encode_cursor([str(version.version), str(version.id)]),
    )


class CompositeValidationSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=ScoreDefinition.Kind.choices, help_text="Expected formula output kind.")
    composition = CompositeConfigSerializer(help_text="Formula and pinned input versions to validate without saving.")
    config = ScoreDefinitionConfigField(
        required=False, help_text="Output configuration to check literal categories and composite scoring rules."
    )


class CompositeValidationResponseSerializer(serializers.Serializer):
    valid = serializers.BooleanField(help_text="Whether the formula and any supplied output configuration are valid.")


class ScoreDefinitionCreateSerializer(ResourceTagsWriteSerializer):
    calculation = serializers.ChoiceField(
        choices=ScoreDefinition.Calculation.choices,
        default=ScoreDefinition.Calculation.REPORTED,
        help_text="Reported or composite. This cannot be changed after creation.",
    )
    composition = CompositeConfigSerializer(
        required=False,
        allow_null=True,
        help_text="Required for composite scorers: expression and exact input versions.",
    )
    name = serializers.CharField(max_length=255, help_text="Human-readable scorer name.")
    short_name = serializers.CharField(
        max_length=40, required=False, allow_blank=True, help_text="Optional compact label. Blank uses the full name."
    )
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


class ScoreDefinitionMetadataSerializer(ResourceTagsWriteSerializer):
    name = serializers.CharField(max_length=255, required=False, help_text="Updated scorer name.")
    short_name = serializers.CharField(
        max_length=40, required=False, allow_blank=True, help_text="Updated compact label. Blank uses the full name."
    )
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
    composition = CompositeConfigSerializer(
        required=False,
        allow_null=True,
        help_text="Required for a composite scorer. Creates a new immutable formula and input selection.",
    )
    short_name = serializers.CharField(
        max_length=40, required=False, allow_blank=True, help_text="Updated compact label, saved with this version."
    )
    name = serializers.CharField(
        max_length=255, required=False, help_text="Updated scorer name, saved with this version."
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Updated scorer description, saved with this version.",
    )
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

    def validate_name(self, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise serializers.ValidationError("`name` cannot be blank.")
        return normalized_value


class ScoreDefinitionFilter(django_filters.FilterSet):
    calculation = django_filters.ChoiceFilter(
        choices=ScoreDefinition.Calculation.choices, help_text="Filter reported or composite scorers."
    )
    input_definition_id = django_filters.UUIDFilter(
        field_name="current_version__inputs__input_version__definition_id",
        distinct=True,
        help_text="Find current composite scorers that depend on this input scorer.",
    )
    created_by = django_filters.NumberFilter(field_name="created_by_id", help_text="Filter by the creator's user ID.")
    search = django_filters.CharFilter(
        method="filter_search",
        help_text="Search scorers by name, short name, or description.",
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
            return queryset.filter(
                Q(name__icontains=value) | Q(short_name__icontains=value) | Q(description__icontains=value)
            )
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
    scope_object_read_actions = ["list", "retrieve", "versions", "retrieve_version", "validate_composition"]
    permission_classes = [AccessControlPermission]
    serializer_class = ScoreDefinitionSerializer
    queryset = ScoreDefinition.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = ScoreDefinitionFilter
    http_method_names = ["get", "post", "patch", "head", "options"]

    def _input_prefetch(self) -> Prefetch:
        return Prefetch(
            "current_version__inputs",
            queryset=ScoreDefinitionInput.objects.for_team(self.team_id, canonical=True)
            .select_related("input_version__definition__current_version")
            .order_by("alias"),
        )

    def safely_get_queryset(
        self, queryset: QuerySet[ScoreDefinition, ScoreDefinition]
    ) -> QuerySet[ScoreDefinition, ScoreDefinition]:
        accessible = self.user_access_control.filter_queryset_by_access_level(
            ScoreDefinition.objects.filter(team_id=self.team_id), include_all_if_admin=True, resource="llm_analytics"
        )
        queryset = (
            queryset.filter(team_id=self.team_id)
            .filter(
                Q(current_version__isnull=True)
                | Q(current_version__in=CompositeScorers.accessible_versions(accessible, team_id=self.team_id))
            )
            .select_related("current_version", "created_by", "updated_by")
            .prefetch_related(self._input_prefetch())
            .annotate(
                dependent_composite_count=Count(
                    "versions__dependents__composite_version__definition",
                    distinct=True,
                    filter=Q(
                        versions__dependents__composite_version__definition__in=accessible,
                        versions__dependents__composite_version__in=CompositeScorers.accessible_versions(
                            accessible, team_id=self.team_id
                        ),
                        versions__dependents__composite_version__definition__archived=False,
                        versions__dependents__composite_version__definition__current_version_id=F(
                            "versions__dependents__composite_version_id"
                        ),
                    ),
                )
            )
            .order_by("name", "id")
        )

        # List defaults to active scorers to mirror the UI; non-boolean `?archived=` values keep that default.
        if self.action == "list":
            archived_param = (self.request.query_params.get("archived") or "").strip().lower()
            if archived_param not in {"true", "false", "1", "0"}:
                queryset = queryset.filter(archived=False)
        elif self.action in {"versions", "retrieve_version"}:
            queryset = self.user_access_control.filter_queryset_by_access_level(queryset, include_all_if_admin=True)

        if self.action == "list":
            tag_query = ResourceTagFilterSerializer(data=self.request.query_params)
            tag_query.is_valid(raise_exception=True)
            queryset = ResourceTags.filter(
                queryset, self.team_id, tag_query.validated_data.get("tags", []), tag_query.validated_data["tag_match"]
            )
        return queryset.prefetch_related(ResourceTags.prefetch())

    @staticmethod
    def _event_properties(definition: ScoreDefinition) -> dict[str, str | bool | int]:
        current_version = definition.current_version.version if definition.current_version else 0

        return {
            "scorer_id": str(definition.id),
            "scorer_name": definition.name,
            "scorer_kind": definition.kind,
            "calculation": definition.calculation,
            "has_description": bool(definition.description),
            "archived": definition.archived,
            "version": current_version,
        }

    @transaction.atomic
    def _create_definition(self, validated_data: dict[str, Any]) -> ScoreDefinition:
        definition_data = dict(validated_data)
        config = definition_data.pop("config")
        composition = definition_data.pop("composition", None)
        CompositeScorers.validate(
            composition=composition,
            calculation=definition_data["calculation"],
            kind=definition_data["kind"],
            config=config,
            team_id=self.team_id,
            user_access_control=self.user_access_control,
        )
        tags = definition_data.pop("tags", [])
        definition_data.pop("archived", None)
        definition_data["description"] = definition_data.get("description") or ""

        definition = ScoreDefinition.objects.create(
            team=self.team,
            created_by=cast(User, self.request.user),
            **definition_data,
        )
        definition.create_new_version(config=config, composition=composition, created_by=cast(User, self.request.user))
        ResourceTags.set(definition, tags)
        return definition

    @transaction.atomic
    def _update_definition_metadata(self, definition: ScoreDefinition, validated_data: dict[str, Any]) -> None:
        definition_data = dict(validated_data)
        changed_fields: list[str] = []
        if "tags" in definition_data:
            tags = definition_data.pop("tags")
            if tags != ResourceTags.names(definition):
                ResourceTags.set(definition, tags)
                changed_fields.append("tags")

        if "description" in definition_data:
            definition_data["description"] = definition_data["description"] or ""

        for field, value in definition_data.items():
            if getattr(definition, field) != value:
                setattr(definition, field, value)
                changed_fields.append(field)

        if not changed_fields:
            return

        definition.updated_by = cast(User, self.request.user)
        definition.save(
            update_fields=[*[field for field in changed_fields if field != "tags"], "updated_at", "updated_by"]
        )
        event_properties: dict[str, str | bool | int | list[str]] = {
            **self._event_properties(definition),
            "changed_fields": changed_fields,
        }
        if "archived" in changed_fields:
            event_properties["archived_new_value"] = definition.archived

        transaction.on_commit(
            lambda: report_user_action(
                self.request.user,
                "llma scorer updated",
                event_properties,
                team=self.team,
                request=self.request,
            )
        )

    @transaction.atomic
    def _create_definition_version(
        self, definition: ScoreDefinition, validated_data: dict[str, Any]
    ) -> ScoreDefinition:
        composition = validated_data.get("composition")
        CompositeScorers.validate(
            composition=composition,
            calculation=definition.calculation,
            kind=definition.kind,
            config=validated_data["config"],
            team_id=self.team_id,
            user_access_control=self.user_access_control,
        )
        definition.create_new_version(
            config=validated_data["config"],
            created_by=cast(User, self.request.user),
            base_version=validated_data.get("base_version"),
            composition=composition,
        )
        # create_new_version holds the row lock until commit. Reload so the metadata comparison sees writes made after get_object().
        definition.refresh_from_db()
        self._update_definition_metadata(
            definition,
            {
                field: validated_data[field]
                for field in ("name", "short_name", "description")
                if field in validated_data
            },
        )
        return definition

    @extend_schema(
        parameters=[
            ResourceTagFilterSerializer,
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                description="Search scorers by name, short name, or description.",
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

        prefetch_related_objects([definition], self._input_prefetch())
        return Response(self.get_serializer(definition).data, status=status.HTTP_201_CREATED)

    @validated_request(
        request_serializer=ScoreDefinitionMetadataSerializer,
        responses={200: OpenApiResponse(response=ScoreDefinitionSerializer)},
    )
    def partial_update(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        definition = self.get_object()
        self._update_definition_metadata(definition, dict(request.validated_data))

        return Response(self.get_serializer(definition).data, status=status.HTTP_200_OK)

    @validated_request(
        request_serializer=CompositeValidationSerializer,
        responses={200: CompositeValidationResponseSerializer},
    )
    @action(detail=False, methods=["post"], pagination_class=None)
    def validate_composition(self, request: ValidatedRequest, **kwargs: object) -> Response:
        CompositeScorers.validate(
            composition=request.validated_data["composition"],
            calculation=ScoreDefinition.Calculation.COMPOSITE,
            kind=request.validated_data["kind"],
            config=request.validated_data.get("config"),
            team_id=self.team_id,
            user_access_control=self.user_access_control,
        )
        return Response(CompositeValidationResponseSerializer({"valid": True}).data)

    @validated_request(
        query_serializer=ScoreDefinitionVersionQuerySerializer,
        operation_id="llm_analytics_score_definitions_versions_list",
        responses={200: ScoreDefinitionVersionPageSerializer},
    )
    @action(detail=True, methods=["get"], pagination_class=None)
    def versions(self, request: ValidatedRequest, **kwargs: object) -> Response:
        definition = self.get_object()
        accessible = self.user_access_control.filter_queryset_by_access_level(
            ScoreDefinition.objects.filter(team_id=self.team_id), include_all_if_admin=True, resource="llm_analytics"
        )
        page = _score_definition_version_page(
            definition,
            allowed_versions=CompositeScorers.accessible_versions(accessible, team_id=self.team_id),
            **request.validated_query_data,
        )
        data = ScoreDefinitionVersionPageSerializer(page).data
        data["next"] = page_link(request, "cursor", page.next_cursor)
        return Response(data)

    @validated_request(
        query_serializer=EmptyQuerySerializer,
        parameters=[OpenApiParameter("version_id", UUID, OpenApiParameter.PATH, description="Immutable version UUID.")],
        responses={200: ScoreDefinitionVersionSerializer},
    )
    @action(detail=True, methods=["get"], url_path=r"versions/(?P<version_id>[^/.]+)", pagination_class=None)
    def retrieve_version(self, request: Request, version_id: str, **kwargs: object) -> Response:
        definition = self.get_object()
        try:
            identity = serializers.UUIDField().run_validation(version_id)
        except serializers.ValidationError as error:
            raise serializers.ValidationError({"version_id": error.detail}) from error
        accessible = self.user_access_control.filter_queryset_by_access_level(
            ScoreDefinition.objects.filter(team_id=self.team_id), include_all_if_admin=True, resource="llm_analytics"
        )
        version = (
            CompositeScorers.accessible_versions(accessible, team_id=self.team_id)
            .select_related("definition", "created_by")
            .filter(definition=definition, id=identity)
            .first()
        )
        if version is None:
            raise NotFound("Scorer version not found.")
        return Response(ScoreDefinitionVersionSerializer(version).data)

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

        prefetch_related_objects([definition], self._input_prefetch())
        return Response(self.get_serializer(definition).data, status=status.HTTP_200_OK)
