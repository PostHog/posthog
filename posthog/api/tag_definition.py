from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import router
from django.db.models import Count, OuterRef, QuerySet, Subquery
from django.db.models.functions import Coalesce

from drf_spectacular.plumbing import force_instance
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import filters, mixins, serializers, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from posthog.api.documentation import PostHogAutoSchema
from posthog.api.pagination import BoundedLimitOffsetPagination
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.auth import SessionAuthentication
from posthog.models import Tag, TaggedItem, Team, User
from posthog.models.utils import strict_fetch
from posthog.permissions import OrganizationAdminReadPermissions, TeamMemberAccessPermission
from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle
from posthog.tag_management import delete_unused_tag, get_merge_preview, merge_tags, rename_tag
from posthog.tag_management_access import tag_management_enabled


class TagDefinitionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier of this project's tag.")
    name = serializers.CharField(read_only=True, help_text="Normalized tag name.")
    usage_count = serializers.IntegerField(
        read_only=True, help_text="Persisted assignments, including soft-deleted items."
    )


class RenameTagRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="New tag name. Existing names must be merged instead.")


class TagDefinitionSchema(PostHogAutoSchema):
    def _get_request_for_media_type(self, serializer, direction="request"):
        serializer = force_instance(serializer)
        if isinstance(serializer, RenameTagRequestSerializer):
            return self.resolve_serializer(serializer, direction).ref, True
        return super()._get_request_for_media_type(serializer, direction)


class TagMergeRequestSerializer(serializers.Serializer):
    target_id = serializers.UUIDField(help_text="Existing destination tag in the same project.")


class TagMergePreviewSerializer(serializers.Serializer):
    source_count = serializers.IntegerField(help_text="Assignments currently using the source tag.")
    target_count = serializers.IntegerField(help_text="Assignments currently using the destination tag.")
    overlap_count = serializers.IntegerField(help_text="Items currently using both tags.")
    result_count = serializers.IntegerField(
        help_text="Destination assignments after deduplicating the current snapshot."
    )
    tag = TagDefinitionSerializer(help_text="The destination tag.")


class TagMergeResultSerializer(serializers.Serializer):
    moved_count = serializers.IntegerField(help_text="Assignments moved to the destination by this merge.")
    overlap_count = serializers.IntegerField(help_text="Overlapping assignments deduplicated by this merge.")
    usage_count = serializers.IntegerField(help_text="Destination assignments after the completed merge.")
    tag = TagDefinitionSerializer(help_text="The surviving destination tag.")


class TagManagementErrorSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="Error category.")
    code = serializers.CharField(help_text="Stable error code.")
    detail = serializers.CharField(help_text="Error message.")
    attr = serializers.CharField(allow_null=True, help_text="Invalid field, if applicable.")


class TagDefinitionPagination(BoundedLimitOffsetPagination):
    default_limit = 100
    max_limit = 100


class TagDefinitionOrderingFilter(filters.OrderingFilter):
    def get_ordering(self, request: Request, queryset: QuerySet, view: APIView) -> list[str]:
        ordering = list(super().get_ordering(request, queryset, view) or ["name"])
        if not any(field.lstrip("-") == "name" for field in ordering):
            ordering.append("name")
        return ordering


class TagManagementSessionPermission(BasePermission):
    def has_permission(self, request: Request, view: object) -> bool:
        return isinstance(request.successful_authenticator, SessionAuthentication)


class TagMutationBurstRateThrottle(PersonalApiKeyOrUserRateThrottle):
    scope = "tag_mutation_burst"
    rate = "30/minute"

    def get_cache_key(self, request: Request, view: APIView) -> str:
        return self.cache_format % {
            "scope": self.scope,
            "ident": f"{self.safely_get_team_id_from_view(view)}:{request.user.pk}",
        }


class TagMutationSustainedRateThrottle(TagMutationBurstRateThrottle):
    scope = "tag_mutation_sustained"
    rate = "300/hour"


@contextmanager
def _tag_errors() -> Iterator[None]:
    try:
        yield
    except Tag.DoesNotExist as error:
        raise NotFound(str(error)) from error
    except DjangoValidationError as error:
        raise ValidationError(error.messages) from error


@extend_schema(
    extensions={"x-product": "core"},
    parameters=[
        OpenApiParameter(
            "X-PostHog-Environment-Id",
            int,
            OpenApiParameter.HEADER,
            description="Environment loaded in this browser tab for rollout targeting. Defaults to the project environment.",
        )
    ],
)
@extend_schema_view(
    list=extend_schema(description="List project tags for organization admins and owners. System tags are excluded."),
    retrieve=extend_schema(responses={200: TagDefinitionSerializer, 404: TagManagementErrorSerializer}),
)
class TagDefinitionViewSet(
    TeamAndOrgViewSetMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    scope_object = "INTERNAL"
    queryset = Tag.objects.all()
    serializer_class = TagDefinitionSerializer
    schema = TagDefinitionSchema()
    pagination_class = TagDefinitionPagination
    permission_classes = [TagManagementSessionPermission, OrganizationAdminReadPermissions, TeamMemberAccessPermission]
    filter_backends = [filters.SearchFilter, TagDefinitionOrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name", "usage_count"]
    ordering = ["name"]
    http_method_names = ["get", "patch", "delete", "post", "head", "options"]

    def get_throttles(self) -> list[BaseThrottle]:
        throttles = super().get_throttles()
        if self.action in {"partial_update", "destroy", "merge"}:
            return [TagMutationBurstRateThrottle(), TagMutationSustainedRateThrottle(), *throttles]
        return throttles

    def initial(self, request: Request, *args: object, **kwargs: object) -> None:
        super().initial(request, *args, **kwargs)
        environment_id = serializers.IntegerField(min_value=1).run_validation(
            request.headers.get("X-PostHog-Environment-Id", self.team.id)
        )
        environment = (
            self.team
            if environment_id == self.team.id
            else Team.objects.filter(id=environment_id, project_id=self.team.project_id).first()
        )
        if environment is None or not tag_management_enabled(
            cast(User, request.user), environment, self.get_serializer_context()
        ):
            raise NotFound()

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        usage_count = (
            TaggedItem.objects.filter(tag_id=OuterRef("pk"))
            .order_by()
            .values("tag_id")
            .annotate(count=Count("id"))
            .values("count")
        )
        queryset = (
            queryset.using(router.db_for_write(Tag))
            .exclude(name__startswith="project-group:")
            .annotate(usage_count=Coalesce(Subquery(usage_count), 0))
        )
        return strict_fetch(queryset) if self.action == "list" else queryset

    @extend_schema(
        request=RenameTagRequestSerializer,
        responses={200: TagDefinitionSerializer, 400: TagManagementErrorSerializer, 404: TagManagementErrorSerializer},
    )
    def partial_update(self, request: Request, **kwargs: object) -> Response:
        serializer = RenameTagRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tag = self.get_object()
        with _tag_errors():
            tag = rename_tag(self.team_id, tag.id, serializer.validated_data["name"], cast(User, request.user))
        return Response(
            TagDefinitionSerializer(
                {"id": tag.id, "name": tag.name, "usage_count": tag.tagged_items.using(tag._state.db).count()}
            ).data
        )

    @extend_schema(responses={204: None, 400: TagManagementErrorSerializer, 404: TagManagementErrorSerializer})
    def destroy(self, request: Request, **kwargs: object) -> Response:
        tag = self.get_object()
        with _tag_errors():
            delete_unused_tag(self.team_id, tag.id, cast(User, request.user))
        return Response(status=204)

    @extend_schema(
        parameters=[TagMergeRequestSerializer],
        responses={
            200: TagMergePreviewSerializer,
            400: TagManagementErrorSerializer,
            404: TagManagementErrorSerializer,
        },
    )
    @action(methods=["GET"], detail=True)
    def merge_preview(self, request: Request, **kwargs: object) -> Response:
        serializer = TagMergeRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        source = self.get_object()
        with _tag_errors():
            preview = get_merge_preview(self.team_id, source.id, serializer.validated_data["target_id"])
        return Response(
            TagMergePreviewSerializer(
                {
                    "source_count": preview.source_count,
                    "target_count": preview.target_count,
                    "overlap_count": preview.overlap_count,
                    "result_count": preview.result_count,
                    "tag": {"id": preview.tag.id, "name": preview.tag.name, "usage_count": preview.target_count},
                }
            ).data
        )

    @extend_schema(
        request=TagMergeRequestSerializer,
        responses={200: TagMergeResultSerializer, 400: TagManagementErrorSerializer, 404: TagManagementErrorSerializer},
    )
    @action(methods=["POST"], detail=True)
    def merge(self, request: Request, **kwargs: object) -> Response:
        serializer = TagMergeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        source = self.get_object()
        with _tag_errors():
            result = merge_tags(
                self.team_id, source.id, serializer.validated_data["target_id"], cast(User, request.user)
            )
        return Response(
            TagMergeResultSerializer(
                {
                    "moved_count": result.moved_count,
                    "overlap_count": result.overlap_count,
                    "usage_count": result.usage_count,
                    "tag": {"id": result.tag.id, "name": result.tag.name, "usage_count": result.usage_count},
                }
            ).data
        )
