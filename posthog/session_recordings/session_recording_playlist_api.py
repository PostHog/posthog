import json
import builtins
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Optional, cast

from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, QuerySet
from django.utils.timezone import now

import structlog
import posthoganalytics
from django_filters.rest_framework import DjangoFilterBackend
from loginas.utils import is_impersonated_session
from rest_framework import request, response, serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination

from posthog.schema import RecordingsQuery

from posthog.api.documentation import extend_schema
from posthog.api.file_system.file_system_logging import log_api_file_system_view
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
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
    SyntheticPlaylistDefinition,
    get_all_synthetic_playlists,
    get_synthetic_playlist,
)
from posthog.utils import relative_date_parse

logger = structlog.get_logger(__name__)

PLAYLIST_COUNT_REDIS_PREFIX = "@posthog/replay/playlist_filters_match_count/"

# Hard cap on the list endpoint's page size to bound memory/CPU cost of the
# batched recordings_counts precompute. Chosen well above typical UI pagination
# (30) so we don't surprise existing callers.
PLAYLIST_LIST_MAX_LIMIT = 500
# Chunk size when looking up SessionRecordingViewed with a large session_id IN clause.
CURRENT_USER_VIEWED_CHUNK_SIZE = 5000
# Cap on how many session_ids we consume per saved-filter Redis payload when
# building the cross-playlist watched lookup. Prevents a single oversized cached
# entry from dominating memory.
MAX_SAVED_FILTER_SESSION_IDS_PER_PLAYLIST = 1000


class SessionRecordingPlaylistPagination(LimitOffsetPagination):
    default_limit = 100
    max_limit = PLAYLIST_LIST_MAX_LIMIT


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
        list(playlist.playlist_items.values_list("recording_id", flat=True)),
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
    synthetic_def = get_synthetic_playlist(playlist.short_id, team=team)
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


def _empty_saved_filters_counts() -> dict[str, int | bool | None]:
    return {
        "count": None,
        "has_more": None,
        "watched_count": None,
        "increased": None,
        "last_refreshed_at": None,
    }


def _saved_filters_counts_from_data(data: dict, viewed_session_ids: set[str]) -> dict[str, int | bool | None]:
    id_list: Optional[list[str]] = data.get("session_ids", None)
    current_count = len(id_list) if id_list else 0
    previous_ids = data.get("previous_ids", None)
    watched_count = len(set(id_list) & viewed_session_ids) if id_list else 0
    return {
        "count": current_count,
        "has_more": data.get("has_more", False),
        "watched_count": watched_count,
        "increased": previous_ids is not None and current_count > len(previous_ids),
        "last_refreshed_at": data.get("refreshed_at", None),
    }


def _batch_current_user_viewed(session_ids: set[str], user: User, team: Team) -> set[str]:
    """Chunk SessionRecordingViewed lookups to avoid degenerate IN-clause plans."""
    if not session_ids:
        return set()
    session_ids_list = list(session_ids)
    if len(session_ids_list) <= CURRENT_USER_VIEWED_CHUNK_SIZE:
        return current_user_viewed(session_ids_list, user, team)
    result: set[str] = set()
    for i in range(0, len(session_ids_list), CURRENT_USER_VIEWED_CHUNK_SIZE):
        chunk = session_ids_list[i : i + CURRENT_USER_VIEWED_CHUNK_SIZE]
        result |= current_user_viewed(chunk, user, team)
    return result


def _attach_empty_recordings_counts(playlists: list[SessionRecordingPlaylist]) -> None:
    """Short-circuit the serializer's per-playlist fallback after a precompute failure.

    The per-playlist path re-hits Postgres and Redis for every collection on the page,
    which amplifies load during a partial outage. Attaching empty prefetched attrs
    makes the serializer return the default empty counts fast without retrying.
    """
    for playlist in playlists:
        if getattr(playlist, "_is_synthetic", False):
            continue
        if not hasattr(playlist, "_prefetched_collection_count"):
            playlist._prefetched_collection_count = {  # type: ignore[attr-defined]  # ty: ignore[invalid-assignment]
                "count": None,
                "watched_count": None,
            }
        if not hasattr(playlist, "_prefetched_saved_filters_count"):
            playlist._prefetched_saved_filters_count = _empty_saved_filters_counts()  # type: ignore[attr-defined]  # ty: ignore[invalid-assignment]


def precompute_recordings_counts(playlists: list[SessionRecordingPlaylist], user: User, team: Team) -> None:
    """Batch-fetch recording counts and viewed status for a page of playlists.

    The per-playlist path in the serializer issues 3 DB queries per collection
    (plus one Redis GET + one DB query when saved-filter data exists), which is
    O(N) round-trips for a list response. This helper collapses that into a
    constant number of queries and attaches the results as `_prefetched_*`
    attributes on each instance so the serializer can consume them.

    Synthetic playlists are skipped — they have their own count path.

    Prefetch contract: any list view that renders SessionRecordingPlaylistSerializer
    with many=True should call this first, or the serializer falls back to the
    original per-playlist queries.
    """
    db_playlists = [p for p in playlists if not getattr(p, "_is_synthetic", False)]
    if not db_playlists:
        return

    playlist_ids = [p.id for p in db_playlists]

    # Defense-in-depth: the current caller (`list()`) passes team-scoped playlists
    # from `safely_get_queryset`, but filtering here keeps the helper safe if it's
    # ever reused by a caller that does not pre-scope.
    base_qs = SessionRecordingPlaylistItem.objects.filter(
        playlist_id__in=playlist_ids,
        playlist__team_id=team.id,
    )

    # Counts via SQL aggregation — avoids materializing non-deleted rows when we
    # only need the count. Matches `.exclude(deleted=True)` semantics on the
    # nullable BooleanField (both True=excluded, False/NULL=included).
    counts_by_playlist: dict[int, int] = dict(
        base_qs.exclude(deleted=True).values("playlist_id").annotate(c=Count("id")).values_list("playlist_id", "c")
    )

    # Separate scan for session_ids — includes soft-deleted rows to preserve the
    # watched-count semantics of the pre-change count_collection_recordings.
    session_ids_by_playlist: dict[int, list[str]] = defaultdict(list)
    for playlist_id, session_id in base_qs.values_list("playlist_id", "recording_id"):
        if session_id is not None:
            session_ids_by_playlist[playlist_id].append(session_id)

    playlists_needing_saved_filters = [p for p in db_playlists if counts_by_playlist.get(p.id, 0) == 0]

    saved_filter_data_by_short_id: dict[str, dict] = {}
    saved_filter_session_ids: set[str] = set()
    if playlists_needing_saved_filters:
        values: list[Optional[str]]
        try:
            redis_client = get_client()
            keys = [f"{PLAYLIST_COUNT_REDIS_PREFIX}{p.short_id}" for p in playlists_needing_saved_filters]
            values = redis_client.mget(keys)
        except Exception as e:
            logger.warning(
                "saved_filters_redis_mget_failed",
                error=str(e),
                team_id=team.id,
                key_count=len(playlists_needing_saved_filters),
            )
            values = [None] * len(playlists_needing_saved_filters)
        for playlist, value in zip(playlists_needing_saved_filters, values):
            if not value:
                continue
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                logger.warning(
                    "saved_filters_redis_payload_malformed",
                    team_id=team.id,
                    playlist_short_id=playlist.short_id,
                )
                continue
            id_list = (parsed.get("session_ids") or [])[:MAX_SAVED_FILTER_SESSION_IDS_PER_PLAYLIST]
            # Write the capped list back into parsed so that the downstream
            # watched_count calculation only considers session IDs we actually
            # looked up viewed status for in _batch_current_user_viewed.
            parsed["session_ids"] = id_list
            saved_filter_data_by_short_id[playlist.short_id] = parsed
            saved_filter_session_ids.update(id_list)

    collection_session_ids: set[str] = {sid for sids in session_ids_by_playlist.values() for sid in sids}
    all_session_ids = collection_session_ids | saved_filter_session_ids
    viewed_session_ids = _batch_current_user_viewed(all_session_ids, user, team)

    for playlist in db_playlists:
        count = counts_by_playlist.get(playlist.id, 0)
        session_ids = session_ids_by_playlist.get(playlist.id, [])
        watched_count = len(set(session_ids) & viewed_session_ids)
        playlist._prefetched_collection_count = {  # type: ignore[attr-defined]
            "count": count if count > 0 else None,
            "watched_count": watched_count,
        }

        if count > 0:
            # Match existing behavior: saved_filters is only loaded when collection is empty.
            continue

        data = saved_filter_data_by_short_id.get(playlist.short_id)
        playlist._prefetched_saved_filters_count = (  # type: ignore[attr-defined]
            _saved_filters_counts_from_data(data, viewed_session_ids)
            if data is not None
            else _empty_saved_filters_counts()
        )


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
    name = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Human-readable name for the playlist.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional description of the playlist's purpose or contents.",
    )
    pinned = serializers.BooleanField(
        required=False,
        help_text="Whether this playlist is pinned to the top of the list.",
    )
    deleted = serializers.BooleanField(
        required=False,
        help_text="Set to true to soft-delete the playlist.",
    )
    filters = serializers.JSONField(
        required=False,
        help_text="JSON object with recording filter criteria. Only used when type is 'filters'. Defines which recordings match this saved filter view. When updating a filters-type playlist, you must include the existing filters alongside any other changes — omitting filters will be treated as removing them.",
    )
    type = serializers.ChoiceField(
        choices=SessionRecordingPlaylist.PlaylistType.choices,
        required=False,
        allow_null=True,
        help_text="Playlist type: 'collection' for manually curated recordings, 'filters' for saved filter views. Required on create, cannot be changed after.",
    )

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
            "is_synthetic",
        ]

    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)

    def get_is_synthetic(self, playlist: SessionRecordingPlaylist) -> bool:
        """Return whether this is a synthetic playlist"""
        return getattr(playlist, "_is_synthetic", False)

    def get_recordings_counts(self, playlist: SessionRecordingPlaylist) -> dict[str, dict[str, int | bool | None]]:
        recordings_counts: dict[str, dict[str, int | bool | None]] = {
            "saved_filters": _empty_saved_filters_counts(),
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
                prefetched_collection = getattr(playlist, "_prefetched_collection_count", None)
                if prefetched_collection is not None:
                    recordings_counts["collection"] = prefetched_collection
                else:
                    recordings_counts["collection"] = count_collection_recordings(playlist, user, team)

                # we only return saved filters if there are no collection recordings
                if recordings_counts["collection"]["count"] is None or recordings_counts["collection"]["count"] == 0:
                    prefetched_saved = getattr(playlist, "_prefetched_saved_filters_count", None)
                    if prefetched_saved is not None:
                        recordings_counts["saved_filters"] = prefetched_saved
                    else:
                        recordings_counts["saved_filters"] = count_saved_filters(playlist, user, team)

        except Exception as e:
            posthoganalytics.capture_exception(e)

        return recordings_counts

    def create(self, validated_data: dict, *args, **kwargs) -> SessionRecordingPlaylist:
        request = self.context["request"]
        team = self.context["get_team"]()

        created_by = validated_data.pop("created_by", request.user)
        playlist_type = validated_data.pop("type", None)
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
            type=playlist_type,
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
        # Prevent updates to synthetic playlists
        if getattr(instance, "_is_synthetic", False):
            raise ValidationError("Cannot update synthetic playlists")

        # type cannot be changed after creation
        validated_data.pop("type", None)

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


@extend_schema(tags=["replay"])
class SessionRecordingPlaylistViewSet(
    TeamAndOrgViewSetMixin, AccessControlViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet
):
    scope_object = "session_recording_playlist"
    scope_object_read_actions = ["list", "retrieve", "recordings"]
    queryset = SessionRecordingPlaylist.objects.all()
    serializer_class = SessionRecordingPlaylistSerializer
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    pagination_class = SessionRecordingPlaylistPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["short_id", "created_by"]
    lookup_field = "short_id"

    def safely_get_object(self, queryset: QuerySet) -> SessionRecordingPlaylist:
        """Override to handle synthetic playlists in retrieve actions"""
        lookup_value = self.kwargs.get(self.lookup_field)

        # Check if this is a synthetic playlist
        if lookup_value and lookup_value.startswith("synthetic-"):
            synthetic_def = get_synthetic_playlist(lookup_value, team=self.team)
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

        # Create synthetic playlist instances (includes both static and dynamic)
        all_synthetic_playlists = get_all_synthetic_playlists(self.team)
        synthetic_instances = [
            create_synthetic_playlist_instance(sp, self.team, cast(User, request.user))
            for sp in all_synthetic_playlists
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

        # Enforce page size on the combined result so synthetic playlists
        # don't cause the response to exceed the requested limit. The paginator
        # already caps DB-backed pages at PLAYLIST_LIST_MAX_LIMIT; clamp here too
        # so the synthetic slice is bounded identically.
        limit = min(int(request.GET.get("limit", 100)), PLAYLIST_LIST_MAX_LIMIT)
        combined = combined[:limit]

        # Batch-fetch recording counts for the page to avoid the per-playlist
        # N+1 queries performed by SessionRecordingPlaylistSerializer.get_recordings_counts.
        # On failure we log and attach empty prefetched attrs so the serializer
        # short-circuits to default empty counts instead of retrying per-playlist
        # (which amplifies load during a Redis/DB partial outage).
        try:
            precompute_recordings_counts(combined, cast(User, request.user), self.team)
        except Exception as e:
            logger.exception(
                "playlist_recordings_counts_precompute_failed",
                team_id=self.team.id,
                page_size=len(combined),
            )
            posthoganalytics.capture_exception(e)
            _attach_empty_recordings_counts(combined)

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
                if request_value in ("synthetic", "new-urls"):
                    # Exclude all DB playlists when filtering for synthetic or new-urls
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
                    # Custom means user-created only, exclude all synthetic playlists
                    return []
                elif request_value == "new-urls":
                    # Filter for only new-urls synthetic playlists
                    filtered = [p for p in filtered if p.short_id.startswith("synthetic-new-url-")]
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
        tag_queries(team_id=self.team.id, product=Product.REPLAY, feature=Feature.QUERY)
        playlist = self.get_object()

        limit = int(request.GET.get("limit", 50))
        offset = int(request.GET.get("offset", 0))

        # Handle synthetic playlists differently
        if getattr(playlist, "_is_synthetic", False):
            synthetic_def = get_synthetic_playlist(playlist.short_id, team=self.team)
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
            # nosemgrep: idor-lookup-without-team (scoped via DRF parent viewset)
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
                # nosemgrep: idor-lookup-without-team (scoped via DRF parent viewset)
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
