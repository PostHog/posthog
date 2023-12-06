from typing import Dict, List, Optional, Any
from django.db.models import Q
import structlog
from django.db import transaction
from django.db.models import QuerySet
from django.utils.timezone import now
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    extend_schema,
    OpenApiParameter,
    extend_schema_view,
    OpenApiExample,
)
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.exceptions import Conflict
from posthog.models import User
from posthog.models.activity_logging.activity_log import (
    Change,
    Detail,
    changes_between,
    log_activity,
    load_activity,
)
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.notebook.notebook import Notebook
from posthog.models.utils import UUIDT
from posthog.permissions import (
    ProjectMembershipNecessaryPermissions,
    TeamMemberAccessPermission,
)
from posthog.settings import DEBUG
from posthog.utils import relative_date_parse

logger = structlog.get_logger(__name__)


def depluralize(string: str | None) -> str | None:
    if not string:
        return None

    if string.endswith("ies"):
        return string[:-3] + "y"
    elif string.endswith("s"):
        return string[:-1]
    else:
        return string


def log_notebook_activity(
    activity: str,
    notebook_id: str,
    notebook_short_id: str,
    notebook_name: str,
    organization_id: UUIDT,
    team_id: int,
    user: User,
    changes: Optional[List[Change]] = None,
) -> None:
    log_activity(
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        item_id=notebook_id,
        scope="Notebook",
        activity=activity,
        detail=Detail(changes=changes, short_id=notebook_short_id, name=notebook_name),
    )


class NotebookSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notebook
        fields = [
            "id",
            "short_id",
            "title",
            "content",
            "text_content",
            "version",
            "deleted",
            "created_at",
            "created_by",
            "last_modified_at",
            "last_modified_by",
        ]
        read_only_fields = [
            "id",
            "short_id",
            "created_at",
            "created_by",
            "last_modified_at",
            "last_modified_by",
        ]

    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)

    def create(self, validated_data: Dict, *args, **kwargs) -> Notebook:
        request = self.context["request"]
        team = self.context["get_team"]()

        created_by = validated_data.pop("created_by", request.user)
        notebook = Notebook.objects.create(
            team=team,
            created_by=created_by,
            last_modified_by=request.user,
            **validated_data,
        )

        log_notebook_activity(
            activity="created",
            notebook_id=notebook.id,
            notebook_short_id=str(notebook.short_id),
            notebook_name=notebook.title,
            organization_id=self.context["request"].user.current_organization_id,
            team_id=team.id,
            user=self.context["request"].user,
        )

        return notebook

    def update(self, instance: Notebook, validated_data: Dict, **kwargs) -> Notebook:
        try:
            before_update = Notebook.objects.get(pk=instance.id)
        except Notebook.DoesNotExist:
            before_update = None

        with transaction.atomic():
            # select_for_update locks the database row so we ensure version updates are atomic
            locked_instance = Notebook.objects.select_for_update().get(pk=instance.pk)

            if validated_data.keys():
                locked_instance.last_modified_at = now()
                locked_instance.last_modified_by = self.context["request"].user

                if validated_data.get("content"):
                    if validated_data.get("version") != locked_instance.version:
                        raise Conflict("Someone else edited the Notebook")

                    validated_data["version"] = locked_instance.version + 1

                updated_notebook = super().update(locked_instance, validated_data)

        changes = changes_between("Notebook", previous=before_update, current=updated_notebook)

        log_notebook_activity(
            activity="updated",
            notebook_id=str(updated_notebook.id),
            notebook_short_id=str(updated_notebook.short_id),
            notebook_name=updated_notebook.title,
            organization_id=self.context["request"].user.current_organization_id,
            team_id=self.context["team_id"],
            user=self.context["request"].user,
            changes=changes,
        )

        return updated_notebook


@extend_schema(
    description="The API for interacting with Notebooks. This feature is in early access and the API can have "
    "breaking changes without announcement.",
)
@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("short_id", exclude=True),
            OpenApiParameter(
                "created_by",
                OpenApiTypes.INT,
                description="The UUID of the Notebook's creator",
                required=False,
            ),
            OpenApiParameter(
                "user",
                description="If any value is provided for this parameter, return notebooks created by the logged in user.",
                required=False,
            ),
            OpenApiParameter(
                "date_from",
                OpenApiTypes.DATETIME,
                description="Filter for notebooks created after this date & time",
                required=False,
            ),
            OpenApiParameter(
                "date_to",
                OpenApiTypes.DATETIME,
                description="Filter for notebooks created before this date & time",
                required=False,
            ),
            OpenApiParameter(
                "contains",
                description="""Filter for notebooks that match a provided filter.
                Each match pair is separated by a colon,
                multiple match pairs can be sent separated by a space or a comma""",
                examples=[
                    OpenApiExample(
                        "Filter for notebooks that have any recording",
                        value="recording:true",
                    ),
                    OpenApiExample(
                        "Filter for notebooks that do not have any recording",
                        value="recording:false",
                    ),
                    OpenApiExample(
                        "Filter for notebooks that have a specific recording",
                        value="recording:the-session-recording-id",
                    ),
                ],
                required=False,
            ),
        ],
    )
)
class NotebookViewSet(StructuredViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = Notebook.objects.all()
    serializer_class = NotebookSerializer
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
    ]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["short_id"]
    # TODO: Remove this once we have released notebooks
    include_in_docs = DEBUG
    lookup_field = "short_id"

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()

        if not self.action.endswith("update"):
            # Soft-deleted notebooks can be brought back with a PATCH request
            queryset = queryset.filter(deleted=False)

        queryset = queryset.select_related("created_by", "last_modified_by", "team")
        if self.action == "list":
            queryset = queryset.filter(deleted=False)
            queryset = self._filter_request(self.request, queryset)

        order = self.request.GET.get("order", None)
        if order:
            queryset = queryset.order_by(order)
        else:
            queryset = queryset.order_by("-last_modified_at")

        return queryset

    def _filter_request(self, request: Request, queryset: QuerySet) -> QuerySet:
        filters = request.GET.dict()

        for key in filters:
            value = request.GET[key]
            if key == "user":
                queryset = queryset.filter(created_by=request.user)
            elif key == "created_by":
                queryset = queryset.filter(created_by__uuid=value)
            elif key == "last_modified_by":
                queryset = queryset.filter(last_modified_by__uuid=value)
            elif key == "date_from":
                queryset = queryset.filter(last_modified_at__gt=relative_date_parse(value, self.team.timezone_info))
            elif key == "date_to":
                queryset = queryset.filter(last_modified_at__lt=relative_date_parse(value, self.team.timezone_info))
            elif key == "search":
                queryset = queryset.filter(
                    # some notebooks have no text_content until next saved, so we need to check the title too
                    # TODO this can be removed once all/most notebooks have text_content
                    Q(title__search=value) | Q(text_content__search=value)
                )
            elif key == "contains":
                contains = value
                match_pairs = contains.replace(",", " ").split(" ")
                # content is a JSONB field that has an array of objects under the key "content"
                # each of those (should) have a "type" field
                # and for recordings that type is "ph-recording"
                # each of those objects can have attrs which is a dict with id for the recording
                for match_pair in match_pairs:
                    splat = match_pair.split(":")
                    target = depluralize(splat[0])
                    match = splat[1] if len(splat) > 1 else None

                    if target:
                        # the JSONB query requires a specific structure
                        basic_structure = List[Dict[str, Any]]
                        nested_structure = basic_structure | List[Dict[str, basic_structure]]

                        presence_match_structure: basic_structure | nested_structure = [{"type": f"ph-{target}"}]

                        try:
                            # We try to parse the match as a number, as query params are always strings,
                            # but an id could be an integer and wouldn't match
                            if isinstance(match, str):  # because mypy
                                match = int(match)
                        except (ValueError, TypeError):
                            pass

                        id_match_structure: basic_structure | nested_structure = [{"attrs": {"id": match}}]
                        if target == "replay-timestamp":
                            # replay timestamps are not at the top level, they're one-level down in a content array
                            presence_match_structure = [{"content": [{"type": f"ph-{target}"}]}]
                            id_match_structure = [{"content": [{"attrs": {"sessionRecordingId": match}}]}]
                        elif target == "query":
                            id_match_structure = [
                                {
                                    "attrs": {
                                        "query": {
                                            "kind": "SavedInsightNode",
                                            "shortId": match,
                                        }
                                    }
                                }
                            ]

                        if match == "true" or match is None:
                            queryset = queryset.filter(content__content__contains=presence_match_structure)
                        elif match == "false":
                            queryset = queryset.exclude(content__content__contains=presence_match_structure)
                        else:
                            queryset = queryset.filter(content__content__contains=presence_match_structure)
                            queryset = queryset.filter(content__content__contains=id_match_structure)

        return queryset

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        serializer = self.get_serializer(instance)

        if str(request.headers.get("If-None-Match")) == str(instance.version):
            return Response(None, 304)

        return Response(serializer.data)

    @action(methods=["GET"], url_path="activity", detail=False)
    def all_activity(self, request: Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="Notebook", team_id=self.team_id, limit=limit, page=page)
        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], url_path="activity", detail=True)
    def activity(self, request: Request, **kwargs):
        notebook = self.get_object()
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(
            scope="Notebook",
            team_id=self.team_id,
            item_id=notebook.id,
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)
