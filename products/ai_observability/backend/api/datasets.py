from collections.abc import Mapping
from typing import NoReturn, cast
from uuid import UUID

from django.db.models import F, OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce
from django.http import Http404

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from posthog.api.documentation import extend_schema
from posthog.api.fields import RepeatedOrCommaSeparatedListField
from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import InternalAPIAuthentication
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import (
    AccessControlPermission,
    APIScopePermission,
    PostHogFeatureFlagPermission,
    TeamMemberAccessPermission,
)
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from products.ai_observability.backend.api.metrics import llma_track_latency
from products.ai_observability.backend.dataset_queries import dataset_item_versions_at_revision
from products.ai_observability.backend.dataset_service import (
    UNSET,
    DatasetMutationConflict,
    DatasetValidationError,
    JSONValue,
    archive_dataset,
    archive_dataset_item,
    create_dataset,
    create_dataset_item,
    restore_dataset,
    restore_dataset_item,
    update_dataset,
    update_dataset_item,
)
from products.ai_observability.backend.models.datasets import Dataset, DatasetItemVersion, DatasetRevision


def _json_value_schema(*, nullable: bool = False) -> dict[str, object]:
    variants: list[dict[str, object]] = [
        {"type": "object", "additionalProperties": True},
        {"type": "array", "items": {}},
        {"type": "string"},
        {"type": "number"},
        {"type": "boolean"},
    ]
    if nullable:
        variants.append({"type": "null"})
    return {"oneOf": variants}


def _dataset_item_update_request_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["base_version"],
        "properties": {
            "base_version": {
                "type": "integer",
                "minimum": 1,
                "description": "Current item version observed by the caller.",
            },
            "input": {
                **_json_value_schema(),
                "description": "Replacement input. Omit to keep the current value.",
            },
            "expected_output": {
                **_json_value_schema(nullable=True),
                "description": "Replacement expected output. Send null to clear it.",
            },
            "metadata": {
                "type": "object",
                "additionalProperties": True,
                "description": "Replacement metadata object. Send an empty object to clear it.",
            },
        },
    }


@extend_schema_field(_json_value_schema(), component_name="DatasetJSONValue")
class DatasetJSONField(serializers.JSONField):
    pass


@extend_schema_field(OpenApiTypes.OBJECT)
class JSONObjectField(serializers.JSONField):
    default_error_messages = {"not_object": "Enter a JSON object."}

    def to_internal_value(self, data: object) -> dict[str, JSONValue]:
        value = super().to_internal_value(cast(dict[str, object] | list[dict[str, object]], data))
        if not isinstance(value, dict):
            self.fail("not_object")
        return cast(dict[str, JSONValue], value)


class DatasetMutationSerializer(serializers.Serializer):
    def to_internal_value(self, data: object) -> dict[str, object]:
        if isinstance(data, Mapping):
            unknown_fields = sorted(set(data) - set(self.fields))
            if unknown_fields:
                raise serializers.ValidationError({field: ["This field is not supported."] for field in unknown_fields})
        return cast(dict[str, object], super().to_internal_value(data))


class DatasetConflictResponseSerializer(serializers.Serializer):
    code = serializers.ChoiceField(
        choices=[
            "dataset_archived",
            "dataset_name_conflict",
            "dataset_item_archived",
            "dataset_item_active",
            "external_id_conflict",
            "stale_version",
        ],
        help_text="Stable code identifying why the mutation was rejected.",
    )
    detail = serializers.CharField(help_text="Explanation of how to resolve the conflict.")
    current_version = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Current item version when the conflict concerns an item.",
    )
    current_item_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Existing item ID when the conflict concerns an external ID.",
    )


def _resolved_dataset_revision(dataset: Dataset) -> int | None:
    annotated_revision = cast(int | None, getattr(dataset, "resolved_current_revision", None))
    if annotated_revision is not None:
        return annotated_revision
    return dataset.current_revision.revision if dataset.current_revision is not None else None


def _resolved_dataset_revision_id(dataset: Dataset) -> UUID | None:
    annotated_revision_id = cast(UUID | None, getattr(dataset, "resolved_current_revision_id", None))
    if annotated_revision_id is not None:
        return annotated_revision_id
    return dataset.current_revision_id


class DatasetReadSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, allow_null=True)
    metadata = JSONObjectField(read_only=True, help_text="JSON object with descriptive dataset metadata.")
    current_revision = serializers.SerializerMethodField(
        help_text="Latest dataset revision, or null before the first item is added.",
    )
    current_revision_id = serializers.SerializerMethodField(
        help_text="ID of the latest committed dataset revision.",
    )
    team_id = serializers.IntegerField(read_only=True, help_text="Project that owns the dataset.")

    class Meta:
        model = Dataset
        fields = [
            "id",
            "name",
            "description",
            "metadata",
            "archived",
            "current_revision",
            "current_revision_id",
            "created_at",
            "updated_at",
            "created_by",
            "team_id",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_current_revision(self, instance: Dataset) -> int | None:
        return _resolved_dataset_revision(instance)

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_current_revision_id(self, instance: Dataset) -> UUID | None:
        return _resolved_dataset_revision_id(instance)


class DatasetCreateSerializer(DatasetMutationSerializer):
    name = serializers.CharField(
        max_length=400,
        trim_whitespace=True,
        help_text="Dataset name. Names are unique within a project.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=10_000,
        help_text="Optional description of what the dataset contains.",
    )
    metadata = JSONObjectField(
        required=False,
        default=dict,
        help_text="Optional JSON object with descriptive dataset metadata.",
    )


class DatasetUpdateSerializer(DatasetMutationSerializer):
    name = serializers.CharField(
        required=False,
        max_length=400,
        trim_whitespace=True,
        help_text="New dataset name. Names are unique within a project.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=10_000,
        help_text="New dataset description.",
    )
    metadata = JSONObjectField(
        required=False,
        help_text="Replacement JSON object for descriptive dataset metadata.",
    )


class DatasetListQuerySerializer(serializers.Serializer):
    id__in = RepeatedOrCommaSeparatedListField(
        child=serializers.UUIDField(),
        required=False,
        min_length=1,
        max_length=100,
        help_text=(
            "Filter to these dataset IDs. Repeat the parameter or pass one comma-separated list, up to 100 IDs."
        ),
    )
    archived = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Return archived datasets instead of active datasets.",
    )
    search = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Search dataset names, descriptions, and metadata.",
    )
    order_by = serializers.ChoiceField(
        required=False,
        default="-created_at",
        choices=["created_at", "-created_at", "updated_at", "-updated_at"],
        help_text="Field and direction used to order results.",
    )


class DatasetRevisionReadSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, allow_null=True)
    dataset_id = serializers.UUIDField(read_only=True, help_text="Dataset this revision belongs to.")
    team_id = serializers.IntegerField(read_only=True, help_text="Project that owns the revision.")

    class Meta:
        model = DatasetRevision
        fields = ["id", "dataset_id", "revision", "created_at", "created_by", "team_id"]
        read_only_fields = fields


class DatasetItemReadSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(
        source="dataset_item_id",
        read_only=True,
        help_text="Stable dataset item ID shared by every version.",
    )
    dataset = serializers.UUIDField(
        source="dataset_item.dataset_id",
        read_only=True,
        help_text="Dataset that owns the item.",
    )
    external_id = serializers.CharField(
        source="dataset_item.external_id",
        read_only=True,
        allow_null=True,
        help_text="Optional caller-owned stable key.",
    )
    version_id = serializers.UUIDField(
        source="id",
        read_only=True,
        help_text="ID of this immutable item version.",
    )
    dataset_revision = serializers.IntegerField(
        source="dataset_revision.revision",
        read_only=True,
        help_text="Dataset revision that introduced this item version.",
    )
    dataset_revision_id = serializers.UUIDField(
        read_only=True,
        help_text="ID of the dataset revision that introduced this item version.",
    )
    input = DatasetJSONField(read_only=True, help_text="Input supplied to the system under test.")
    expected_output = DatasetJSONField(
        read_only=True,
        allow_null=True,
        help_text="Optional user-authored expected output.",
    )
    source_output = DatasetJSONField(
        read_only=True,
        allow_null=True,
        help_text="Optional actual output captured from the source trace.",
    )
    metadata = JSONObjectField(read_only=True, help_text="JSON object with item metadata.")
    created_at = serializers.DateTimeField(
        source="dataset_item.created_at",
        read_only=True,
        help_text="When the stable item was created.",
    )
    updated_at = serializers.DateTimeField(
        source="dataset_item.updated_at",
        read_only=True,
        allow_null=True,
        help_text="When the item last received a new version.",
    )
    created_by = UserBasicSerializer(
        source="dataset_item.created_by",
        read_only=True,
        allow_null=True,
    )
    version_created_at = serializers.DateTimeField(
        source="created_at",
        read_only=True,
        help_text="When this immutable version was created.",
    )
    version_created_by = UserBasicSerializer(source="created_by", read_only=True, allow_null=True)
    team_id = serializers.IntegerField(read_only=True, help_text="Project that owns the item.")

    class Meta:
        model = DatasetItemVersion
        fields = [
            "id",
            "dataset",
            "external_id",
            "version",
            "version_id",
            "dataset_revision",
            "dataset_revision_id",
            "archived",
            "input",
            "expected_output",
            "source_output",
            "metadata",
            "source_trace_id",
            "source_event_id",
            "source_timestamp",
            "created_at",
            "updated_at",
            "created_by",
            "version_created_at",
            "version_created_by",
            "team_id",
        ]
        read_only_fields = fields


class DatasetItemCreateSerializer(DatasetMutationSerializer):
    dataset = serializers.UUIDField(help_text="Dataset that will own the item.")
    external_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=255,
        help_text="Optional case-sensitive stable key used for idempotent creates.",
    )
    input = DatasetJSONField(
        allow_null=False,
        help_text="Input supplied to the system under test. Any non-null JSON value is accepted.",
    )
    expected_output = DatasetJSONField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional user-authored expected output.",
    )
    source_output = DatasetJSONField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional actual output captured from the source trace.",
    )
    metadata = JSONObjectField(
        required=False,
        default=dict,
        help_text="Optional JSON object with item metadata.",
    )
    source_trace_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=255,
        help_text="Trace ID copied from the source event.",
    )
    source_event_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=255,
        help_text="Event ID copied from the source trace.",
    )
    source_timestamp = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Timestamp needed to retrieve the event-backed source trace.",
    )


class DatasetItemUpdateSerializer(DatasetMutationSerializer):
    base_version = serializers.IntegerField(
        min_value=1,
        help_text="Current item version observed by the caller.",
    )
    input = DatasetJSONField(
        required=False,
        allow_null=False,
        help_text="Replacement input. Omit to keep the current value.",
    )
    expected_output = DatasetJSONField(
        required=False,
        allow_null=True,
        help_text="Replacement expected output. Send null to clear it.",
    )
    metadata = JSONObjectField(
        required=False,
        help_text="Replacement metadata object. Send an empty object to clear it.",
    )


class DatasetItemArchiveSerializer(DatasetMutationSerializer):
    base_version = serializers.IntegerField(
        min_value=1,
        help_text="Current item version observed by the caller.",
    )


class DatasetItemRestoreSerializer(DatasetItemArchiveSerializer):
    source_version = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="Historical version to copy. Omit to restore the archived version's content.",
    )


class DatasetItemListQuerySerializer(serializers.Serializer):
    dataset = serializers.UUIDField(help_text="Dataset whose items should be returned.")
    revision = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Return the exact dataset snapshot at this revision.",
    )
    archived = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Return archived items instead of active items.",
    )


class DatasetPagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 100


class DatasetItemPagination(LimitOffsetPagination):
    default_limit = 10
    max_limit = 25


class DatasetItemParentAccessControlPermission(AccessControlPermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        dataset_view = cast(GenericViewSet, view)
        if dataset_view.action != "create":
            return super().has_permission(request, view)

        # Item creation targets an existing dataset, so specific dataset grants apply.
        dataset_view.action = "partial_update"
        try:
            return super().has_permission(request, view)
        finally:
            dataset_view.action = "create"

    def has_object_permission(self, request: Request, view: APIView, obj: object) -> bool:
        if isinstance(obj, Dataset):
            dataset = obj
        elif isinstance(obj, DatasetItemVersion):
            dataset = obj.dataset_item.dataset
        else:
            return False
        return super().has_object_permission(request, view, dataset)


def _validation_error_response(error: DatasetValidationError) -> NoReturn:
    raise serializers.ValidationError({error.field: [error.detail]})


def _conflict_response(error: DatasetMutationConflict) -> Response:
    payload: dict[str, object] = {"code": error.code, "detail": error.detail}
    if error.current_version is not None:
        payload["current_version"] = error.current_version
    if error.current_item_id is not None:
        payload["current_item_id"] = error.current_item_id
    return Response(payload, status=status.HTTP_409_CONFLICT)


def _item_version_queryset() -> QuerySet[DatasetItemVersion, DatasetItemVersion]:
    return DatasetItemVersion.objects.unscoped().select_related(
        "created_by",
        "dataset_revision",
        "dataset_item",
        "dataset_item__created_by",
        "dataset_item__dataset",
    )


def _dataset_queryset() -> QuerySet[Dataset, Dataset]:
    latest_revision = DatasetRevision.objects.unscoped().filter(dataset_id=OuterRef("id")).order_by("-revision")
    return (
        Dataset.objects.unscoped()
        .select_related("created_by", "current_revision")
        .annotate(
            resolved_current_revision=Coalesce(
                F("current_revision__revision"),
                Subquery(latest_revision.values("revision")[:1]),
            ),
            resolved_current_revision_id=Coalesce(
                F("current_revision_id"),
                Subquery(latest_revision.values("id")[:1]),
            ),
        )
    )


def _current_item_version_queryset() -> QuerySet[DatasetItemVersion, DatasetItemVersion]:
    latest_version_id = (
        DatasetItemVersion.objects.unscoped()
        .filter(dataset_item_id=OuterRef("dataset_item_id"))
        .order_by("-version")
        .values("id")[:1]
    )
    return _item_version_queryset().filter(
        id=Coalesce(
            F("dataset_item__current_version_id"),
            Subquery(latest_version_id),
        )
    )


class DatasetViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, GenericViewSet):
    scope_object = "dataset"
    scope_object_read_actions = ["list", "retrieve", "revisions"]
    scope_object_write_actions = ["create", "partial_update", "archive", "restore"]
    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = "llm-analytics-datasets"
    pagination_class = DatasetPagination
    serializer_class = DatasetReadSerializer
    queryset = _dataset_queryset()
    http_method_names = ["get", "post", "patch", "put", "head", "options"]

    def _should_skip_parents_filter(self) -> bool:
        return True

    def safely_get_queryset(self, queryset: QuerySet[Dataset, Dataset]) -> QuerySet[Dataset, Dataset]:
        return queryset.filter(team_id=self.team.id)

    def _filter_queryset_by_access_level(self, queryset: QuerySet[Dataset, Dataset]) -> QuerySet[Dataset, Dataset]:
        if self.action != "list":
            return queryset
        return self.user_access_control.filter_queryset_by_access_level(queryset, include_all_if_admin=True)

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.action == "create":
            return DatasetCreateSerializer
        if self.action == "partial_update":
            return DatasetUpdateSerializer
        if self.action == "revisions":
            return DatasetRevisionReadSerializer
        return DatasetReadSerializer

    @extend_schema(
        parameters=[DatasetListQuerySerializer],
        responses=DatasetReadSerializer(many=True),
        description="List active datasets by default, or archived datasets when requested.",
        tags=["AI observability"],
    )
    @llma_track_latency("llma_datasets_list")
    @monitor(feature=None, endpoint="llma_datasets_list", method="GET")
    def list(self, request: Request, *args: object, **kwargs: object) -> Response:
        query_serializer = DatasetListQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        query = query_serializer.validated_data

        queryset = self.filter_queryset(self.get_queryset()).filter(archived=query["archived"])
        if dataset_ids := query.get("id__in"):
            queryset = queryset.filter(id__in=dataset_ids)
        if search := query.get("search"):
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(description__icontains=search) | Q(metadata__icontains=search)
            )
        queryset = queryset.order_by(query["order_by"], "id")

        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(DatasetReadSerializer(page, many=True).data)
        return Response(DatasetReadSerializer(queryset, many=True).data)

    @extend_schema(
        responses=DatasetReadSerializer,
        description="Retrieve an active or archived dataset.",
        tags=["AI observability"],
    )
    @llma_track_latency("llma_datasets_retrieve")
    @monitor(feature=None, endpoint="llma_datasets_retrieve", method="GET")
    def retrieve(self, request: Request, *args: object, **kwargs: object) -> Response:
        return Response(DatasetReadSerializer(self.get_object()).data)

    @extend_schema(
        request=DatasetCreateSerializer,
        responses={
            201: DatasetReadSerializer,
            409: DatasetConflictResponseSerializer,
        },
        description="Create an empty dataset. Its first revision is created with its first item.",
        tags=["AI observability"],
    )
    @llma_track_latency("llma_datasets_create")
    @monitor(feature=None, endpoint="llma_datasets_create", method="POST")
    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = DatasetCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            dataset = create_dataset(
                team=self.team,
                created_by=cast(User, request.user),
                name=data["name"],
                description=data["description"],
                metadata=data["metadata"],
            )
        except DatasetValidationError as error:
            _validation_error_response(error)
        except DatasetMutationConflict as error:
            return _conflict_response(error)

        report_user_action(
            request.user,
            "llma dataset created",
            {
                "dataset_id": str(dataset.id),
                "has_description": bool(dataset.description),
                "has_metadata": bool(dataset.metadata),
            },
            team=self.team,
            request=request,
        )
        return Response(DatasetReadSerializer(dataset).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=DatasetUpdateSerializer,
        responses={
            200: DatasetReadSerializer,
            409: DatasetConflictResponseSerializer,
        },
        description="Update descriptive dataset fields without changing its revision.",
        tags=["AI observability"],
    )
    @llma_track_latency("llma_datasets_partial_update")
    @monitor(feature=None, endpoint="llma_datasets_partial_update", method="PATCH")
    def partial_update(self, request: Request, *args: object, **kwargs: object) -> Response:
        current = self.get_object()
        serializer = DatasetUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            dataset = update_dataset(
                team_id=self.team.id,
                dataset_id=current.id,
                name=data.get("name", UNSET),
                description=data.get("description", UNSET),
                metadata=data.get("metadata", UNSET),
            )
        except DatasetValidationError as error:
            _validation_error_response(error)
        except DatasetMutationConflict as error:
            return _conflict_response(error)

        return Response(DatasetReadSerializer(dataset).data)

    @extend_schema(
        operation_id="datasets_archive",
        request=None,
        responses=DatasetReadSerializer,
        description="Archive a dataset. Archived datasets remain readable and reject item mutations.",
        tags=["AI observability"],
    )
    @action(detail=True, methods=["post"])
    def archive(self, request: Request, *args: object, **kwargs: object) -> Response:
        current = self.get_object()
        dataset = archive_dataset(team_id=self.team.id, dataset_id=current.id)
        return Response(DatasetReadSerializer(dataset).data)

    @extend_schema(
        operation_id="datasets_restore",
        request=None,
        responses=DatasetReadSerializer,
        description="Restore an archived dataset without changing its item states.",
        tags=["AI observability"],
    )
    @action(detail=True, methods=["post"])
    def restore(self, request: Request, *args: object, **kwargs: object) -> Response:
        current = self.get_object()
        dataset = restore_dataset(team_id=self.team.id, dataset_id=current.id)
        return Response(DatasetReadSerializer(dataset).data)

    @extend_schema(
        operation_id="datasets_revisions_list",
        responses=DatasetRevisionReadSerializer(many=True),
        description="List immutable dataset revisions, newest first.",
        tags=["AI observability"],
    )
    @action(detail=True, methods=["get"])
    def revisions(self, request: Request, *args: object, **kwargs: object) -> Response:
        dataset = self.get_object()
        queryset = (
            DatasetRevision.objects.for_team(self.team.id, canonical=True)
            .filter(dataset_id=dataset.id)
            .select_related("created_by")
            .order_by("-revision")
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(DatasetRevisionReadSerializer(page, many=True).data)
        return Response(DatasetRevisionReadSerializer(queryset, many=True).data)


class DatasetItemViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "dataset"
    scope_object_read_actions = ["list", "retrieve", "versions"]
    scope_object_write_actions = ["create", "partial_update", "archive", "restore"]
    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = "llm-analytics-datasets"
    pagination_class = DatasetItemPagination
    serializer_class = DatasetItemReadSerializer
    queryset = _current_item_version_queryset()
    lookup_field = "dataset_item_id"
    http_method_names = ["get", "post", "patch", "head", "options"]

    def _should_skip_parents_filter(self) -> bool:
        return True

    def dangerously_get_permissions(self) -> list[BasePermission]:
        if isinstance(self.request.successful_authenticator, InternalAPIAuthentication):
            return [IsAuthenticated()]
        return [
            IsAuthenticated(),
            APIScopePermission(),
            DatasetItemParentAccessControlPermission(),
            TeamMemberAccessPermission(),
            PostHogFeatureFlagPermission(),
        ]

    def safely_get_queryset(
        self,
        queryset: QuerySet[DatasetItemVersion, DatasetItemVersion],
    ) -> QuerySet[DatasetItemVersion, DatasetItemVersion]:
        accessible_datasets: QuerySet[Dataset, Dataset] = Dataset.objects.for_team(self.team.id, canonical=True)
        accessible_datasets = self.user_access_control.filter_queryset_by_access_level(
            accessible_datasets,
            include_all_if_admin=True,
        )
        return queryset.filter(
            team_id=self.team.id,
            dataset_item__dataset_id__in=Subquery(accessible_datasets.values("id")),
        )

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.action == "create":
            return DatasetItemCreateSerializer
        if self.action == "partial_update":
            return DatasetItemUpdateSerializer
        if self.action == "archive":
            return DatasetItemArchiveSerializer
        if self.action == "restore":
            return DatasetItemRestoreSerializer
        return DatasetItemReadSerializer

    def _get_dataset(self, dataset_id: UUID) -> Dataset:
        try:
            dataset = _dataset_queryset().filter(team_id=self.team.id).get(id=dataset_id)
        except Dataset.DoesNotExist as error:
            raise Http404 from error
        self.check_object_permissions(self.request, dataset)
        return dataset

    @extend_schema(
        parameters=[DatasetItemListQuerySerializer],
        responses=DatasetItemReadSerializer(many=True),
        description="List a dataset's current items or its exact contents at a prior revision.",
        tags=["AI observability"],
    )
    @llma_track_latency("llma_dataset_items_list")
    @monitor(feature=None, endpoint="llma_dataset_items_list", method="GET")
    def list(self, request: Request, *args: object, **kwargs: object) -> Response:
        query_serializer = DatasetItemListQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        query = query_serializer.validated_data
        dataset = self._get_dataset(query["dataset"])
        archived: bool = query["archived"]

        revision: int | None = query.get("revision")
        if revision is None:
            queryset = self.get_queryset().filter(
                dataset_item__dataset_id=dataset.id,
                archived=archived,
            )
        else:
            current_revision = _resolved_dataset_revision(dataset)
            if current_revision is None or revision > current_revision:
                raise Http404("Dataset revision not found.")

            version_ids = dataset_item_versions_at_revision(
                team_id=self.team.id,
                dataset_id=dataset.id,
                revision=revision,
                archived=archived,
            ).values("id")
            queryset = _item_version_queryset().filter(
                id__in=Subquery(version_ids),
            )

        queryset = queryset.order_by("-dataset_item__created_at", "dataset_item_id")
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(DatasetItemReadSerializer(page, many=True).data)
        return Response(DatasetItemReadSerializer(queryset, many=True).data)

    @extend_schema(
        responses=DatasetItemReadSerializer,
        description="Retrieve the current version of an active or archived item.",
        tags=["AI observability"],
    )
    @llma_track_latency("llma_dataset_items_retrieve")
    @monitor(feature=None, endpoint="llma_dataset_items_retrieve", method="GET")
    def retrieve(self, request: Request, *args: object, **kwargs: object) -> Response:
        return Response(DatasetItemReadSerializer(self.get_object()).data)

    @extend_schema(
        request=DatasetItemCreateSerializer,
        responses={
            200: DatasetItemReadSerializer,
            201: DatasetItemReadSerializer,
            409: DatasetConflictResponseSerializer,
        },
        description=(
            "Create an item and its first immutable version. An identical external ID retry returns the existing item. "
            "If the matching item is archived, the submitted content is restored as a new active version."
        ),
        tags=["AI observability"],
    )
    @llma_track_latency("llma_dataset_items_create")
    @monitor(feature=None, endpoint="llma_dataset_items_create", method="POST")
    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = DatasetItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        dataset = self._get_dataset(data["dataset"])
        try:
            result = create_dataset_item(
                team_id=self.team.id,
                dataset_id=dataset.id,
                created_by=cast(User, request.user),
                input=data["input"],
                expected_output=data["expected_output"],
                source_output=data["source_output"],
                metadata=data["metadata"],
                external_id=data.get("external_id"),
                source_trace_id=data.get("source_trace_id"),
                source_event_id=data.get("source_event_id"),
                source_timestamp=data.get("source_timestamp"),
            )
        except DatasetValidationError as error:
            _validation_error_response(error)
        except DatasetMutationConflict as error:
            return _conflict_response(error)

        if result.created:
            report_user_action(
                request.user,
                "llma dataset item created",
                {
                    "dataset_item_id": str(result.item.id),
                    "dataset_id": str(dataset.id),
                    "has_expected_output": result.version.expected_output is not None,
                    "has_source_output": result.version.source_output is not None,
                    "has_provenance": result.version.source_trace_id is not None,
                },
                team=self.team,
                request=request,
            )
        response_status = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        return Response(DatasetItemReadSerializer(result.version).data, status=response_status)

    @extend_schema(
        request={"application/json": _dataset_item_update_request_schema()},
        responses={
            200: DatasetItemReadSerializer,
            409: DatasetConflictResponseSerializer,
        },
        description="Create a new immutable item version from editable fields.",
        tags=["AI observability"],
    )
    @llma_track_latency("llma_dataset_items_partial_update")
    @monitor(feature=None, endpoint="llma_dataset_items_partial_update", method="PATCH")
    def partial_update(self, request: Request, *args: object, **kwargs: object) -> Response:
        current = self.get_object()
        serializer = DatasetItemUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = update_dataset_item(
                team_id=self.team.id,
                dataset_id=current.dataset_item.dataset_id,
                item_id=current.dataset_item_id,
                created_by=cast(User, request.user),
                base_version=data["base_version"],
                input=data.get("input", UNSET),
                expected_output=data.get("expected_output", UNSET),
                metadata=data.get("metadata", UNSET),
            )
        except DatasetValidationError as error:
            _validation_error_response(error)
        except DatasetMutationConflict as error:
            return _conflict_response(error)
        return Response(DatasetItemReadSerializer(result.version).data)

    @extend_schema(
        operation_id="dataset_items_archive",
        request=DatasetItemArchiveSerializer,
        responses={
            200: DatasetItemReadSerializer,
            409: DatasetConflictResponseSerializer,
        },
        description="Archive an active item by creating a new immutable version.",
        tags=["AI observability"],
    )
    @action(detail=True, methods=["post"])
    def archive(self, request: Request, *args: object, **kwargs: object) -> Response:
        current = self.get_object()
        serializer = DatasetItemArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = archive_dataset_item(
                team_id=self.team.id,
                dataset_id=current.dataset_item.dataset_id,
                item_id=current.dataset_item_id,
                created_by=cast(User, request.user),
                base_version=serializer.validated_data["base_version"],
            )
        except DatasetMutationConflict as error:
            return _conflict_response(error)
        return Response(DatasetItemReadSerializer(result.version).data)

    @extend_schema(
        operation_id="dataset_items_restore",
        request=DatasetItemRestoreSerializer,
        responses={
            200: DatasetItemReadSerializer,
            409: DatasetConflictResponseSerializer,
        },
        description="Restore an archived item by copying content into a new immutable version.",
        tags=["AI observability"],
    )
    @action(detail=True, methods=["post"])
    def restore(self, request: Request, *args: object, **kwargs: object) -> Response:
        current = self.get_object()
        serializer = DatasetItemRestoreSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = restore_dataset_item(
                team_id=self.team.id,
                dataset_id=current.dataset_item.dataset_id,
                item_id=current.dataset_item_id,
                created_by=cast(User, request.user),
                base_version=serializer.validated_data["base_version"],
                source_version=serializer.validated_data.get("source_version"),
            )
        except DatasetItemVersion.DoesNotExist as error:
            raise Http404("Dataset item version not found.") from error
        except DatasetMutationConflict as error:
            return _conflict_response(error)
        return Response(DatasetItemReadSerializer(result.version).data)

    @extend_schema(
        operation_id="dataset_items_versions_list",
        responses=DatasetItemReadSerializer(many=True),
        description="List every immutable version of an item, newest first.",
        tags=["AI observability"],
    )
    @action(detail=True, methods=["get"])
    def versions(self, request: Request, *args: object, **kwargs: object) -> Response:
        current = self.get_object()
        queryset = _item_version_queryset().filter(
            team_id=self.team.id,
            dataset_item_id=current.dataset_item_id,
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(DatasetItemReadSerializer(page, many=True).data)
        return Response(DatasetItemReadSerializer(queryset, many=True).data)
