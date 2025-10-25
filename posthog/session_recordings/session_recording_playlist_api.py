import json
import builtins
from datetime import UTC, datetime
from typing import Any, Optional, cast

from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
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
from posthog.api.file_system.file_system_logging import log_api_file_system_view
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
from posthog.session_recordings.synthetic_playlists import (
    SYNTHETIC_PLAYLISTS,
    SyntheticPlaylistDefinition,
    get_synthetic_playlist,
)
from posthog.utils import relative_date_parse

logger = structlog.get_logger(__name__)

PLAYLIST_COUNT_REDIS_PREFIX = "@posthog/replay/playlist_filters_match_count/"


def create_synthetic_playlist_instance(
    synthetic_def: SyntheticPlaylistDefinition, team: Team, user: User
) -> SessionRecordingPlaylist:
    """
    Create an in-memory SessionRecordingPlaylist instance for a synthetic playlist.
    This instance is not saved to the database.
    """
    # Create an unsaved instance with all the necessary fields
    instance = SessionRecordingPlaylist(
        id=synthetic_def.id,
        short_id=synthetic_def.short_id,
        name=synthetic_def.name,
        description=synthetic_def.description,
        team=team,
        pinned=False,
        deleted=False,
        filters={},  # Synthetic playlists don't use traditional filters
        type=synthetic_def.type,
        created_at=None,
        created_by=None,
        last_modified_at=None,
        last_modified_by=None,
    )
    # Mark it as synthetic so we can identify it later
    instance._is_synthetic = True  # type: ignore
    instance._synthetic_metadata = synthetic_def.metadata  # type: ignore
    return instance


def count_collection_recordings(
    playlist: SessionRecordingPlaylist, user: User, team: Team
) -> dict[str, int | bool | None]:
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


def count_synthetic_playlist(
    playlist: SessionRecordingPlaylist, user: User, team: Team
) -> dict[str, int | bool | None]:
    """Count recordings in a synthetic playlist using efficient database-level counting"""
    synthetic_def = get_synthetic_playlist(playlist.short_id)
    if not synthetic_def:
        return {
            "count": None,
            "has_more": None,
            "watched_count": None,
            "increased": None,
            "last_refreshed_at": None,
        }

    # Use the count function for efficient database-level counting
    count = synthetic_def.count_session_ids(team, user)

    # For watched_count, we still need to load session IDs since we're checking user-specific viewed status
    # But only if count > 0
    if count > 0:
        session_ids = synthetic_def.get_session_ids(team, user)
        watched_count = len(current_user_viewed(session_ids, user, team))
    else:
        watched_count = 0

    return {
        "count": count if count > 0 else None,
        "has_more": False,  # We don't paginate synthetic playlists (yet)
        "watched_count": watched_count,
        "increased": None,  # We don't track historical changes for synthetic playlists
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
    is_synthetic = serializers.SerializerMethodField()

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
            "is_synthetic",
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
            "is_synthetic",
        ]

    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)

    def get_is_synthetic(self, playlist: SessionRecordingPlaylist) -> bool:
        """Return whether this is a synthetic playlist"""
        return getattr(playlist, "_is_synthetic", False)

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

            # Handle synthetic playlists differently
            if getattr(playlist, "_is_synthetic", False):
                recordings_counts["collection"] = count_synthetic_playlist(playlist, user, team)
            else:
                recordings_counts["collection"] = count_collection_recordings(playlist, user, team)

                # we only return saved filters if there are no collection recordings
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
        # Prevent updates to synthetic playlists
        if getattr(instance, "_is_synthetic", False):
            raise ValidationError("Cannot update synthetic playlists")

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

    def safely_get_object(self, queryset: QuerySet) -> SessionRecordingPlaylist:
        """Override to handle synthetic playlists in retrieve actions"""
        lookup_value = self.kwargs.get(self.lookup_field)

        # Check if this is a synthetic playlist
        if lookup_value and lookup_value.startswith("synthetic-"):
            synthetic_def = get_synthetic_playlist(lookup_value)
            if synthetic_def:
                return create_synthetic_playlist_instance(synthetic_def, self.team, cast(User, self.request.user))

        # Fall back to normal DB lookup
        return super().safely_get_object(queryset)

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        """Override list to include synthetic playlists"""
        # Get regular DB playlists
        queryset = self.safely_get_queryset(self.get_queryset())

        # Get the total count of DB playlists before pagination
        db_count = queryset.count()

        # Apply pagination to DB playlists
        page = self.paginate_queryset(queryset)

        # Check if we're on the first page by looking at offset parameter
        # Synthetic playlists should only appear on the first page to avoid duplicates
        offset = int(request.GET.get("offset", 0))
        page_number = int(request.GET.get("page", 1))
        is_first_page = offset == 0 and page_number == 1

        # Create synthetic playlist instances
        synthetic_instances = [
            create_synthetic_playlist_instance(sp, self.team, cast(User, request.user)) for sp in SYNTHETIC_PLAYLISTS
        ]

        # Filter synthetic playlists based on request filters
        filtered_synthetics = self._filter_synthetic_playlists(request, synthetic_instances)

        # Only include synthetic playlists on the first page
        synthetics_to_include = filtered_synthetics if is_first_page else []

        # Combine DB and synthetic playlists
        if page is not None:
            combined = list(page) + synthetics_to_include
        else:
            combined = list(queryset) + synthetics_to_include

        # Apply ordering to the combined list
        combined = self._order_playlists(request, combined)

        serializer = self.get_serializer(combined, many=True)

        # Calculate total count including synthetic playlists (only counted once on first page)
        total_count = db_count + len(filtered_synthetics)

        if page is not None:
            # Manually construct paginated response with correct count
            paginated_response = self.get_paginated_response(serializer.data)
            # Override the count with the total including synthetic playlists
            paginated_response.data["count"] = total_count
            return paginated_response
        return response.Response({"count": total_count, "next": None, "previous": None, "results": serializer.data})

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
            elif key == "created_by":
                queryset = queryset.filter(created_by=request_value)
            elif key == "type":
                if request_value == SessionRecordingPlaylist.PlaylistType.COLLECTION:
                    queryset = queryset.filter(type=SessionRecordingPlaylist.PlaylistType.COLLECTION)
                elif request_value == SessionRecordingPlaylist.PlaylistType.FILTERS:
                    queryset = queryset.filter(type=SessionRecordingPlaylist.PlaylistType.FILTERS)
            elif key == "collection_type":
                if request_value == "synthetic":
                    queryset = queryset.none()
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

    def _filter_synthetic_playlists(
        self, request: request.Request, playlists: builtins.list[SessionRecordingPlaylist]
    ) -> builtins.list[SessionRecordingPlaylist]:
        """Apply request filters to synthetic playlists"""
        filters = request.GET.dict()
        filtered = playlists

        for key in filters:
            request_value = filters[key]
            if key == "user" or key == "created_by":
                # Synthetic playlists don't have a created_by, filter them out if user/created_by filter is set
                return []
            elif key == "type":
                if request_value == SessionRecordingPlaylist.PlaylistType.FILTERS:
                    # Synthetic playlists are collections, so exclude them when filtering for filters type
                    return []
                elif request_value == SessionRecordingPlaylist.PlaylistType.COLLECTION:
                    # Keep all synthetic playlists (they're all collection type)
                    pass
            elif key == "collection_type":
                if request_value == "custom":
                    return []
            elif key == "pinned":
                # Synthetic playlists are never pinned, so exclude them
                return []
            elif key == "search":
                search_term = request_value.lower()
                filtered = [
                    p
                    for p in filtered
                    if search_term in (p.name or "").lower() or search_term in (p.description or "").lower()
                ]
            # date_from, date_to, and session_recording_id don't apply to synthetic playlists

        return filtered

    def _order_playlists(
        self, request: request.Request, playlists: builtins.list[SessionRecordingPlaylist]
    ) -> builtins.list[SessionRecordingPlaylist]:
        order = request.GET.get("order", "-last_modified_at")
        is_descending = order.startswith("-")

        def get_sort_key(playlist: SessionRecordingPlaylist):
            if order in ("name", "-name"):
                return (playlist.name or playlist.derived_name or "").lower()

            timestamp = playlist.created_at if order in ("created_at", "-created_at") else playlist.last_modified_at

            if not timestamp:
                is_synthetic = getattr(playlist, "_is_synthetic", False)
                timestamp = datetime.max.replace(tzinfo=UTC) if is_synthetic else datetime.min.replace(tzinfo=UTC)

            return timestamp

        try:
            return sorted(playlists, key=get_sort_key, reverse=is_descending)
        except Exception:
            return playlists

    # As of now, you can only "update" a session recording by adding or removing a recording from a static playlist
    @action(methods=["GET"], detail=True, url_path="recordings")
    def recordings(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        playlist = self.get_object()

        limit = int(request.GET.get("limit", 50))
        offset = int(request.GET.get("offset", 0))

        # Handle synthetic playlists differently
        if getattr(playlist, "_is_synthetic", False):
            synthetic_def = get_synthetic_playlist(playlist.short_id)
            if synthetic_def:
                playlist_items = synthetic_def.get_session_ids(self.team, cast(User, request.user), limit, offset)
            else:
                playlist_items = []
        else:
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

        viewed_at = now()

        # only create if it doesn't exist
        try:
            with transaction.atomic():
                SessionRecordingPlaylistViewed.objects.create(
                    user=user,
                    playlist=playlist,
                    team=team,
                    viewed_at=viewed_at,
                )
        except IntegrityError:
            # that's okay... if the viewed at clashes then we're ok skipping creation
            pass

        log_api_file_system_view(request, playlist, viewed_at=viewed_at)

        return response.Response({"success": True})
