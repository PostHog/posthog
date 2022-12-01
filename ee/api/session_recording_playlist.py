from typing import Any, Dict, List, Optional

import structlog
from django.db.models import Q, QuerySet
from django.utils.timezone import now
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.constants import SESSION_RECORDINGS_PLAYLIST_FREE_COUNT, AvailableFeature
from posthog.models import SessionRecordingPlaylist, SessionRecordingPlaylistItem, Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, changes_between, log_activity
from posthog.models.team.team import get_available_features_for_team
from posthog.models.utils import UUIDT
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.rate_limit import PassThroughClickHouseBurstRateThrottle, PassThroughClickHouseSustainedRateThrottle
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


class SessionRecordingPlaylistItemSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    created_at = serializers.DateTimeField()

    def to_representation(self, instance):
        return {
            "id": instance.session_id,
            "created_at": instance.created_at,
        }


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

    def create(self, validated_data: Dict, *args, **kwargs) -> SessionRecordingPlaylist:
        request = self.context["request"]
        team = Team.objects.get(id=self.context["team_id"])

        self._check_can_create_playlist(team)

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
            changes=changes,
        )

        return updated_playlist

    def _check_can_create_playlist(self, team: Team) -> bool:
        available_features = get_available_features_for_team(team.id)
        playlist_count = SessionRecordingPlaylist.objects.filter(deleted=False, team=team).count()

        if (
            AvailableFeature.RECORDINGS_PLAYLISTS not in (available_features or [])
            and playlist_count >= SESSION_RECORDINGS_PLAYLIST_FREE_COUNT
        ):
            raise PermissionDenied("You have hit the limit for playlists for this team.")

        return True

    # def _update_recording_playlists(
    #     self, request, playlist_ids: List[int], session_id: str, recording_start_time: Optional[datetime]
    # ) -> List[int]:
    #     session_recording = SessionRecording(
    #         request=request,
    #         team=self.team,
    #         session_recording_id=session_id,
    #         recording_start_time=recording_start_time,
    #     )

    #     if not session_recording.query_session_exists():
    #         raise exceptions.NotFound("Session not found")

    #     old_playlist_ids = [
    #         item.playlist_id
    #         for item in SessionRecordingPlaylistItem.objects.filter(session_id=session_id).exclude(deleted=True).all()
    #     ]
    #     new_playlist_ids = [
    #         playlist.id
    #         for playlist in SessionRecordingPlaylist.objects.filter(id__in=playlist_ids).exclude(deleted=True).all()
    #     ]
    #     ids_to_add = [id for id in new_playlist_ids if id not in old_playlist_ids]
    #     ids_to_remove = [id for id in old_playlist_ids if id not in new_playlist_ids]

    #     candidate_playlists = SessionRecordingPlaylist.objects.filter(id__in=ids_to_add).exclude(deleted=True)

    #     # Determine which records to update and which to create
    #     records = []
    #     records_to_create = []
    #     records_to_update = []

    #     for playlist in candidate_playlists:
    #         existing_playlist_item = SessionRecordingPlaylistItem.objects.filter(
    #             playlist=playlist, session_id=session_id
    #         ).first()

    #         existing_playlist_item_id = None
    #         if existing_playlist_item is not None:
    #             existing_playlist_item_id = existing_playlist_item.id

    #         records.append(
    #             {
    #                 "id": existing_playlist_item_id,
    #                 "playlist": playlist,
    #             }
    #         )

    #     for record in records:
    #         if record["id"] is not None:
    #             records_to_update.append(record)
    #         else:
    #             records_to_create.append(record)

    #     for record in records_to_create:
    #         record.pop("id")

    #     SessionRecordingPlaylistItem.objects.bulk_create(
    #         [
    #             SessionRecordingPlaylistItem(
    #                 session_id=session_id, playlist=cast(SessionRecordingPlaylist, values.get("playlist"))
    #             )
    #             for values in records_to_create
    #         ]
    #     )
    #     SessionRecordingPlaylistItem.objects.bulk_update(
    #         [
    #             SessionRecordingPlaylistItem(id=cast(int, values.get("id")), deleted=False)
    #             for values in records_to_update
    #         ],
    #         ["deleted"],
    #         batch_size=500,
    #     )

    #     if ids_to_remove:
    #         SessionRecordingPlaylistItem.objects.filter(playlist_id__in=ids_to_remove, session_id=session_id).update(
    #             deleted=True
    #         )

    #     return list(
    #         (
    #             SessionRecordingPlaylistItem.objects.filter(session_id=session_id)
    #             .exclude(deleted=True)
    #             .values_list("playlist_id", flat=True)
    #         )
    #     )


class SessionRecordingPlaylistViewSet(StructuredViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = SessionRecordingPlaylist.objects.all()
    serializer_class = SessionRecordingPlaylistSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    throttle_classes = [PassThroughClickHouseBurstRateThrottle, PassThroughClickHouseSustainedRateThrottle]
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
            elif key == "pinned":
                queryset = queryset.filter(pinned=True)
            elif key == "date_from":
                queryset = queryset.filter(last_modified_at__gt=relative_date_parse(request.GET["date_from"]))
            elif key == "date_to":
                queryset = queryset.filter(last_modified_at__lt=relative_date_parse(request.GET["date_to"]))
            elif key == "search":
                queryset = queryset.filter(
                    Q(name__icontains=request.GET["search"]) | Q(derived_name__icontains=request.GET["search"])
                )
            elif key == "session_recording_id":
                queryset = queryset.filter(playlist_items__session_id=request.GET["session_recording_id"])
        return queryset

    # As of now, you can only "update" a session recording by adding or removing a recording from a static playlist
    @action(methods=["GET"], detail=True, url_path="recordings")
    def recordings(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        playlist = self.get_object()
        playlist_items = SessionRecordingPlaylistItem.objects.filter(playlist=playlist).exclude(deleted=True)

        serialized = SessionRecordingPlaylistItemSerializer(data=playlist_items, many=True)
        serialized.is_valid(raise_exception=False)

        return response.Response({"results": serialized.data})

    # As of now, you can only "update" a session recording by adding or removing a recording from a static playlist
    @action(methods=["POST", "DELETE"], detail=True, url_path="recordings/(?P<session_recording_id>[^/.]+)")
    def modify_recordings(
        self, request: request.Request, session_recording_id: str, *args: Any, **kwargs: Any
    ) -> response.Response:
        playlist = self.get_object()

        if request.method == "POST":
            playlist_item, created = SessionRecordingPlaylistItem.objects.get_or_create(
                playlist=playlist,
                session_id=session_recording_id,
            )

            return response.Response({"success": True})

        if request.method == "DELETE":
            playlist_item = SessionRecordingPlaylistItem.objects.get(
                playlist=playlist,
                session_id=session_recording_id,
            )

            if playlist_item:
                playlist_item.delete()

            return response.Response({"success": True})

        raise NotImplementedError()
