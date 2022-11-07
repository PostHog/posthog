from typing import Dict, List, Optional

import structlog
from django.db.models import Q, QuerySet
from django.utils.timezone import now
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import request, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import SessionRecordingPlaylist, Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, changes_between, log_activity
from posthog.models.utils import UUIDT
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.rate_limit import PassThroughClickHouseBurstRateThrottle, PassThroughClickHouseSustainedRateThrottle
from posthog.utils import relative_date_parse, str_to_bool

logger = structlog.get_logger(__name__)


def log_playlist_activity(
    activity: str,
    playlist: SessionRecordingPlaylist,
    playlist_id: int,
    playlist_short_id: str,
    organization_id: UUIDT,
    team_id: int,
    user: User,
    changes: Optional[List[Change]] = None,
) -> None:
    """
    Insight id and short_id are passed separately as some activities (like delete) alter the Insight instance

    The experiments feature creates insights without a name, this does not log those
    """

    playlist_name: Optional[str] = playlist.name if playlist.name else playlist.derived_name
    if playlist_name:
        log_activity(
            organization_id=organization_id,
            team_id=team_id,
            user=user,
            item_id=playlist_id,
            scope="SessionRecordingPlaylist",
            activity=activity,
            detail=Detail(name=playlist_name, changes=changes, short_id=playlist_short_id),
        )


class SessionRecordingPlaylistSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionRecordingPlaylist
        fields = [
            "id",
            "short_id",
            "name",
            "derived_name",
            "description",
            "team",
            "pinned",
            "created_at",
            "created_by",
            "deleted",
            "saved",
            "filters",
            "last_modified_at",
            "last_modified_by",
        ]
        read_only_fields = "short_id"

    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)

    def create(self, validated_data: Dict, *args, **kwargs) -> SessionRecordingPlaylist:
        request = self.context["request"]
        team = Team.objects.get(id=self.context["team_id"])

        created_by = validated_data.pop("created_by", request.user)
        playlist = SessionRecordingPlaylist.objects.create(
            team=team, created_by=created_by, last_modified_by=request.user, **validated_data
        )

        log_playlist_activity(
            activity="created",
            playlist=playlist,
            playlist_id=playlist.id,
            playlist_short_id=playlist.short_id,
            organization_id=self.context["request"].user.current_organization_id,
            team_id=team.id,
            user=self.context["request"].user,
        )

        return playlist

    def update(self, instance: SessionRecordingPlaylist, validated_data: Dict, **kwargs) -> SessionRecordingPlaylist:

        try:
            before_update = SessionRecordingPlaylist.objects.get(pk=instance.id)
        except SessionRecordingPlaylist.DoesNotExist:
            before_update = None

        if validated_data.keys() & SessionRecordingPlaylist.MATERIAL_INSIGHT_FIELDS:
            instance.last_modified_at = now()
            instance.last_modified_by = self.context["request"].user

        updated_playlist = super().update(instance, validated_data)
        changes = changes_between("SessionRecordingPlaylist", previous=before_update, current=updated_playlist)

        log_playlist_activity(
            activity="updated",
            playlist=updated_playlist,
            playlist_id=updated_playlist.id,
            playlist_short_id=updated_playlist.short_id,
            organization_id=self.context["request"].user.current_organization_id,
            team_id=self.context["team_id"],
            user=self.context["request"].user,
            changes=changes,
        )

        return updated_playlist


class SessionRecordingPlaylistViewSet(StructuredViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = SessionRecordingPlaylist.objects.all()
    serializer_class = SessionRecordingPlaylistSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    throttle_classes = [PassThroughClickHouseBurstRateThrottle, PassThroughClickHouseSustainedRateThrottle]
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (csvrenderers.CSVRenderer,)
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["short_id", "created_by"]
    include_in_docs = True

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
            queryset = queryset.order_by("order")

        return queryset

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        filters = request.GET.dict()

        for key in filters:
            if key == "saved":
                queryset = queryset.filter(saved=str_to_bool(request.GET["saved"]))
            elif key == "user":
                queryset = queryset.filter(created_by=request.user)
            elif key == "date_from":
                queryset = queryset.filter(last_modified_at__gt=relative_date_parse(request.GET["date_from"]))
            elif key == "date_to":
                queryset = queryset.filter(last_modified_at__lt=relative_date_parse(request.GET["date_to"]))
            elif key == "search":
                queryset = queryset.filter(
                    Q(name__icontains=request.GET["search"]) | Q(derived_name__icontains=request.GET["search"])
                )
        return queryset
