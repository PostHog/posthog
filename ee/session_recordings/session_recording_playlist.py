import json
from typing import Any, Optional

import structlog
from django.db.models import Q, QuerySet
from django.utils.timezone import now
from django_filters.rest_framework import DjangoFilterBackend
from loginas.utils import is_impersonated_session
from rest_framework import request, response, serializers, viewsets
from posthog.api.utils import action
from rest_framework.exceptions import PermissionDenied

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.constants import SESSION_RECORDINGS_FILTER_IDS, AvailableFeature
from posthog.models import (
    SessionRecording,
    SessionRecordingPlaylist,
    SessionRecordingPlaylistItem,
    Team,
    User,
)
from posthog.models.activity_logging.activity_log import (
    Change,
    Detail,
    changes_between,
    log_activity,
)
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.team.team import check_is_feature_available_for_team
from posthog.models.utils import UUIDT
from posthog.rate_limit import (
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
)
from posthog.session_recordings.session_recording_api import list_recordings_response
from posthog.utils import relative_date_parse

logger = structlog.get_logger(__name__)


def log_playlist_activity(
    activity: str,
    playlist: SessionRecordingPlaylist,
    playlist_id: int,
    playlist_short_id: str,
    organization_id: UUIDT,
    team_id: int,
    user: User,
    was_impersonated: bool,
    changes: Optional[list[Change]] = None,
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
            was_impersonated=was_impersonated,
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
            "pinned",
            "created_at",
            "created_by",
            "deleted",
            "filters",
            "last_modified_at",
            "last_modified_by",
        ]
        read_only_fields = [
            "id",
            "short_id",
            "team",
            "created_at",
            "created_by",
            "last_modified_at",
            "last_modified_by",
        ]

    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)

    def create(self, validated_data: dict, *args, **kwargs) -> SessionRecordingPlaylist:
        request = self.context["request"]
        team = self.context["get_team"]()

        self._check_can_create_playlist(team)

        created_by = validated_data.pop("created_by", request.user)
        playlist = SessionRecordingPlaylist.objects.create(
            team=team,
            created_by=created_by,
            last_modified_by=request.user,
            **validated_data,
        )

        log_playlist_activity(
            activity="created",
            playlist=playlist,
            playlist_id=playlist.id,
            playlist_short_id=playlist.short_id,
            organization_id=self.context["request"].user.current_organization_id,
            team_id=team.id,
            user=self.context["request"].user,
            was_impersonated=is_impersonated_session(self.context["request"]),
        )

        return playlist

    def update(self, instance: SessionRecordingPlaylist, validated_data: dict, **kwargs) -> SessionRecordingPlaylist:
        try:
            before_update = SessionRecordingPlaylist.objects.get(pk=instance.id)
        except SessionRecordingPlaylist.DoesNotExist:
            before_update = None

        if validated_data.keys() & SessionRecordingPlaylist.MATERIAL_PLAYLIST_FIELDS:
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
            was_impersonated=is_impersonated_session(self.context["request"]),
            changes=changes,
        )

        return updated_playlist

    def _check_can_create_playlist(self, team: Team) -> bool:
        playlist_count = SessionRecordingPlaylist.objects.filter(deleted=False, team=team).count()
        if not check_is_feature_available_for_team(team.pk, AvailableFeature.RECORDINGS_PLAYLISTS, playlist_count):
            raise PermissionDenied("You have hit the limit for playlists for this team.")
        return True


class SessionRecordingPlaylistViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "session_recording_playlist"
    queryset = SessionRecordingPlaylist.objects.all()
    serializer_class = SessionRecordingPlaylistSerializer
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["short_id", "created_by"]
    lookup_field = "short_id"

    def safely_get_queryset(self, queryset) -> QuerySet:
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
            elif key == "pinned":
                queryset = queryset.filter(pinned=True)
            elif key == "date_from":
                queryset = queryset.filter(
                    last_modified_at__gt=relative_date_parse(request.GET["date_from"], self.team.timezone_info)
                )
            elif key == "date_to":
                queryset = queryset.filter(
                    last_modified_at__lt=relative_date_parse(request.GET["date_to"], self.team.timezone_info)
                )
            elif key == "search":
                queryset = queryset.filter(
                    Q(name__icontains=request.GET["search"]) | Q(derived_name__icontains=request.GET["search"])
                )
            elif key == "session_recording_id":
                queryset = queryset.filter(playlist_items__recording_id=request.GET["session_recording_id"])
        return queryset

    # As of now, you can only "update" a session recording by adding or removing a recording from a static playlist
    @action(methods=["GET"], detail=True, url_path="recordings")
    def recordings(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        playlist = self.get_object()
        playlist_items = list(
            SessionRecordingPlaylistItem.objects.filter(playlist=playlist)
            .exclude(deleted=True)
            .order_by("-created_at")
            .values_list("recording_id", flat=True)
        )

        filter = SessionRecordingsFilter(request=request, team=self.team)
        filter = filter.shallow_clone({SESSION_RECORDINGS_FILTER_IDS: json.dumps(playlist_items)})

        return list_recordings_response(filter, request, self.get_serializer_context())

    # As of now, you can only "update" a session recording by adding or removing a recording from a static playlist
    @action(
        methods=["POST", "DELETE"],
        detail=True,
        url_path="recordings/(?P<session_recording_id>[^/.]+)",
    )
    def modify_recordings(
        self,
        request: request.Request,
        session_recording_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> response.Response:
        playlist = self.get_object()

        # TODO: Maybe we need to save the created_at date here properly to help with filtering
        if request.method == "POST":
            recording, _ = SessionRecording.objects.get_or_create(
                session_id=session_recording_id,
                team=self.team,
                defaults={"deleted": False},
            )
            playlist_item, created = SessionRecordingPlaylistItem.objects.get_or_create(
                playlist=playlist, recording=recording
            )

            return response.Response({"success": True})

        if request.method == "DELETE":
            playlist_item = SessionRecordingPlaylistItem.objects.get(playlist=playlist, recording=session_recording_id)  # type: ignore

            if playlist_item:
                playlist_item.delete()

            return response.Response({"success": True})

        raise NotImplementedError()
