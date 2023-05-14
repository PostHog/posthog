from typing import Dict, List, Optional

import structlog
from django.db.models import Q, QuerySet
from django.utils.timezone import now
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, changes_between, log_activity, load_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.notebook.notebook import Notebook
from posthog.models.utils import UUIDT
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.utils import relative_date_parse

logger = structlog.get_logger(__name__)


def log_notebook_activity(
    activity: str,
    notebook_id: str,
    notebook_short_id: str,
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
        detail=Detail(changes=changes, short_id=notebook_short_id),
    )


class NotebookSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notebook
        fields = [
            "id",
            "short_id",
            "title",
            "content",
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

        self._check_can_create_notebook(team)

        created_by = validated_data.pop("created_by", request.user)
        notebook = Notebook.objects.create(
            team=team, created_by=created_by, last_modified_by=request.user, **validated_data
        )

        log_notebook_activity(
            activity="created",
            notebook_id=notebook.id,
            notebook_short_id=str(notebook.short_id),
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

        if validated_data.keys():
            instance.last_modified_at = now()
            instance.last_modified_by = self.context["request"].user

        updated_notebook = super().update(instance, validated_data)
        changes = changes_between("Notebook", previous=before_update, current=updated_notebook)

        log_notebook_activity(
            activity="updated",
            notebook_id=str(updated_notebook.id),
            notebook_short_id=str(updated_notebook.short_id),
            organization_id=self.context["request"].user.current_organization_id,
            team_id=self.context["team_id"],
            user=self.context["request"].user,
            changes=changes,
        )

        return updated_notebook

    @staticmethod
    def _check_can_create_notebook(team: Team) -> bool:
        notebook_count = Notebook.objects.filter(deleted=False, team=team).count()
        if notebook_count > 10:
            raise PermissionDenied("You have hit the limit for notebooks for this team. Delete some to create more.")
        return True


class NotebookViewSet(StructuredViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = Notebook.objects.all()
    serializer_class = NotebookSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["short_id", "created_by"]
    include_in_docs = True
    lookup_field = "short_id"

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()

        if not self.action.endswith("update"):
            # Soft-deleted insights can be brought back with a PATCH request
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

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        filters = request.GET.dict()

        for key in filters:
            if key == "user":
                queryset = queryset.filter(created_by=request.user)
            elif key == "date_from":
                queryset = queryset.filter(last_modified_at__gt=relative_date_parse(request.GET["date_from"]))
            elif key == "date_to":
                queryset = queryset.filter(last_modified_at__lt=relative_date_parse(request.GET["date_to"]))
            elif key == "search":
                queryset = queryset.filter(Q(title__icontains=request.GET["search"]))
        return queryset

    @action(methods=["GET"], url_path="activity", detail=False)
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="Notebook", team_id=self.team_id, limit=limit, page=page)
        return activity_page_response(activity_page, limit, page, request)
