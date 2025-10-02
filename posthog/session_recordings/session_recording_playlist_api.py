import json
from typing import Any, Optional, cast

from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError
from django.db.models import Q, QuerySet
from django.utils.timezone import now

import structlog
import posthoganalytics
from django_filters.rest_framework import DjangoFilterBackend
from loginas.utils import is_impersonated_session
from rest_framework import request, response, serializers, viewsets
from rest_framework.exceptions import ValidationError

from posthog.schema import RecordingsQuery

from posthog.api.documentation import extend_schema
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.models import SessionRecording, SessionRecordingPlaylist, SessionRecordingPlaylistItem, User
from posthog.models.activity_logging.activity_log import Change, Detail, changes_between, log_activity
from posthog.models.team.team import Team
from posthog.models.utils import UUIDT
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin
from posthog.redis import get_client
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylistViewed
from posthog.session_recordings.session_recording_api import (
    current_user_viewed,
    list_recordings_from_query,
    list_recordings_response,
    query_as_params_to_dict,
)
from posthog.utils import relative_date_parse

logger = structlog.get_logger(__name__)

PLAYLIST_COUNT_REDIS_PREFIX = "@posthog/replay/playlist_filters_match_count/"


def count_pinned_recordings(playlist: SessionRecordingPlaylist, user: User, team: Team) -> dict[str, int | bool | None]:
    playlist_items: QuerySet[SessionRecordingPlaylistItem] = playlist.playlist_items.exclude(deleted=True)
    watched_playlist_items = current_user_viewed(
        # mypy can't detect that it's safe to pass queryset to list() 🤷
        list(playlist.playlist_items.values_list("session_id", flat=True)),  # type: ignore
        user,
        team,
    )

    item_count = playlist_items.count()
    watched_count = len(watched_playlist_items)

    return {
        "count": item_count if item_count > 0 else None,
        "watched_count": watched_count,
    }


def count_saved_filters(playlist: SessionRecordingPlaylist, user: User, team: Team) -> dict[str, int | bool | None]:
    redis_client = get_client()
    counts = redis_client.get(f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}")

    if counts:
        count_data = json.loads(counts)
        id_list: Optional[list[str]] = count_data.get("session_ids", None)
        current_count = len(id_list) if id_list else 0
        previous_ids = count_data.get("previous_ids", None)
        return {
            "count": current_count,
            "has_more": count_data.get("has_more", False),
            "watched_count": len(current_user_viewed(id_list, user, team)) if id_list else 0,
            "increased": previous_ids is not None and current_count > len(previous_ids),
            "last_refreshed_at": count_data.get("refreshed_at", None),
        }
    return {
        "count": None,
        "has_more": None,
        "watched_count": None,
        "increased": None,
        "last_refreshed_at": None,
    }


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


class SessionRecordingPlaylistSerializer(serializers.ModelSerializer, UserAccessControlSerializerMixin):
    recordings_counts = serializers.SerializerMethodField()
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)

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
            "recordings_counts",
            "type",
            "_create_in_folder",
        ]
        read_only_fields = [
            "id",
            "short_id",
            "team",
            "created_at",
            "created_by",
            "last_modified_at",
            "last_modified_by",
            "recordings_counts",
            "type",
        ]

    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)

    def get_recordings_counts(self, playlist: SessionRecordingPlaylist) -> dict[str, dict[str, int | bool | None]]:
        recordings_counts: dict[str, dict[str, int | bool | None]] = {
            "saved_filters": {
                "count": None,
                "has_more": None,
                "watched_count": None,
                "increased": None,
                "last_refreshed_at": None,
            },
            "collection": {
                "count": None,
                "watched_count": None,
            },
        }

        try:
            user = self.context["request"].user
            team = self.context["get_team"]()

            recordings_counts["collection"] = count_pinned_recordings(playlist, user, team)

            # we only return saved filters if there are no pinned recordings
            if recordings_counts["collection"]["count"] is None or recordings_counts["collection"]["count"] == 0:
                recordings_counts["saved_filters"] = count_saved_filters(playlist, user, team)

        except Exception as e:
            posthoganalytics.capture_exception(e)

        return recordings_counts

    def create(self, validated_data: dict, *args, **kwargs) -> SessionRecordingPlaylist:
        request = self.context["request"]
        team = self.context["get_team"]()

        created_by = validated_data.pop("created_by", request.user)
        # because 'type' is in read_only_fields, it won't be in validated_data.
        # Get it from initial_data to allow setting it on creation.
        playlist_type = self.initial_data.get("type", None)
        if not playlist_type or playlist_type not in ["collection", "filters"]:
            raise ValidationError("Must provide a valid playlist type: either filters or collection")

        if playlist_type == "collection" and len(validated_data.get("filters", {})) > 0:
            raise ValidationError("You cannot create a collection with filters")

        if playlist_type == "filters" and len(validated_data.get("filters", {})) == 0:
            raise ValidationError("You must provide a valid filters when creating a saved filter")

        playlist = SessionRecordingPlaylist.objects.create(
            team=team,
            created_by=created_by,
            last_modified_by=request.user,
            type=playlist_type,  # Explicitly set the type using the value from initial_data
            **validated_data,  # Pass remaining validated data (which won't include 'type')
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

        if instance.type == "collection" and len(validated_data.get("filters", {})) > 0:
            # Allow empty filters object, only reject if it has actual filter keys
            raise ValidationError("You cannot update a collection to add filters")
        if instance.type == "filters" and len(validated_data.get("filters", {})) == 0:
            raise ValidationError("You cannot remove all filters when updating a saved filter")

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


class SessionRecordingPlaylistViewSet(
    TeamAndOrgViewSetMixin, AccessControlViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet
):
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
            request_value = filters[key]
            if key == "user":
                queryset = queryset.filter(created_by=request.user)
            elif key == "type":
                if request_value == SessionRecordingPlaylist.PlaylistType.COLLECTION:
                    queryset = queryset.filter(type=SessionRecordingPlaylist.PlaylistType.COLLECTION)
                elif request_value == SessionRecordingPlaylist.PlaylistType.FILTERS:
                    queryset = queryset.filter(type=SessionRecordingPlaylist.PlaylistType.FILTERS)
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

        # For collections, create a minimal query with only session_ids
        if playlist.type == SessionRecordingPlaylist.PlaylistType.COLLECTION:
            query = RecordingsQuery(session_ids=playlist_items, date_from="-1y", date_to=None)
        else:
            data_dict = query_as_params_to_dict(request.GET.dict())
            query = RecordingsQuery.model_validate(data_dict)
            query.session_ids = playlist_items

        return list_recordings_response(
            list_recordings_from_query(query, cast(User, request.user), team=self.team),
            context=self.get_serializer_context(),
        )

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
            if playlist.type == SessionRecordingPlaylist.PlaylistType.FILTERS:
                raise serializers.ValidationError("Cannot add recordings to a playlist that is type 'filters'.")

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
            playlist_item = SessionRecordingPlaylistItem.objects.get(playlist=playlist, recording=session_recording_id)

            if playlist_item:
                playlist_item.delete()

            return response.Response({"success": True})

        raise ValidationError("Only POST and DELETE methods are supported")

    @extend_schema(exclude=True)
    @action(
        methods=["POST"],
        detail=True,
        url_path="recordings/bulk_add",
    )
    def bulk_add_recordings(
        self,
        request: request.Request,
        *args: Any,
        **kwargs: Any,
    ) -> response.Response:
        playlist = self.get_object()

        # Get session_recording_ids from request body
        session_recording_ids = request.data.get("session_recording_ids", [])

        if not session_recording_ids or not isinstance(session_recording_ids, list):
            raise ValidationError("session_recording_ids must be provided as a non-empty array")

        if len(session_recording_ids) > 20:
            raise ValidationError("Cannot process more than 20 recordings at once")

        if playlist.type == SessionRecordingPlaylist.PlaylistType.FILTERS:
            raise ValidationError("Cannot add recordings to a playlist that is type 'filters'.")

        added_count = 0
        for session_recording_id in session_recording_ids:
            try:
                recording, _ = SessionRecording.objects.get_or_create(
                    session_id=session_recording_id,
                    team=self.team,
                    defaults={"deleted": False},
                )
                playlist_item, created = SessionRecordingPlaylistItem.objects.get_or_create(
                    playlist=playlist, recording=recording
                )
                if created:
                    added_count += 1
            except Exception as e:
                logger.warning(
                    "failed_to_add_recording_to_playlist",
                    session_recording_id=session_recording_id,
                    playlist_id=playlist.short_id,
                    error=str(e),
                )

        logger.info(
            "bulk_recordings_added_to_playlist",
            playlist_id=playlist.short_id,
            added_count=added_count,
            total_requested=len(session_recording_ids),
        )

        return response.Response(
            {"success": True, "added_count": added_count, "total_requested": len(session_recording_ids)}
        )

    @extend_schema(exclude=True)
    @action(
        methods=["POST"],
        detail=True,
        url_path="recordings/bulk_delete",
    )
    def bulk_delete_recordings(
        self,
        request: request.Request,
        *args: Any,
        **kwargs: Any,
    ) -> response.Response:
        playlist = self.get_object()

        # Get session_recording_ids from request body
        session_recording_ids = request.data.get("session_recording_ids", [])

        if not session_recording_ids or not isinstance(session_recording_ids, list):
            raise ValidationError("session_recording_ids must be provided as a non-empty array")

        if len(session_recording_ids) > 20:
            raise ValidationError("Cannot process more than 20 recordings at once")

        deleted_count = 0
        for session_recording_id in session_recording_ids:
            try:
                playlist_item = SessionRecordingPlaylistItem.objects.get(
                    playlist=playlist, recording=session_recording_id
                )
                playlist_item.delete()
                deleted_count += 1
            except SessionRecordingPlaylistItem.DoesNotExist:
                pass  # Already deleted or never existed

        logger.info(
            "bulk_recordings_deleted_from_playlist",
            playlist_id=playlist.short_id,
            deleted_count=deleted_count,
            total_requested=len(session_recording_ids),
        )

        return response.Response(
            {"success": True, "deleted_count": deleted_count, "total_requested": len(session_recording_ids)}
        )

    @extend_schema(exclude=True)
    @action(methods=["POST"], detail=True)
    def playlist_viewed(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        playlist = self.get_object()
        user = cast(User | AnonymousUser, request.user)
        team = self.team

        if user.is_anonymous:
            raise ValidationError("Only authenticated users can mark a playlist as viewed.")

        # only create if it doesn't exist
        try:
            SessionRecordingPlaylistViewed.objects.create(user=user, playlist=playlist, team=team)
        except IntegrityError:
            # that's okay... if the viewed at clashes then we're ok skipping creation
            pass

        return response.Response({"success": True})
