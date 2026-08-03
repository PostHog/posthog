import re
import time
import shlex
import builtins
from collections.abc import Callable
from typing import Any, cast
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Case, F, IntegerField, Q, QuerySet, Value, When
from django.db.models.functions import Concat, Lower
from django.utils import timezone

import structlog
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import filters, pagination, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.canvas_artifacts import create_canvas_artifact_url
from posthog.api.file_system.access_levels import FileSystemAccessLevelSerializerMixin
from posthog.api.file_system.canvas_build_service import (
    MAX_ACTIVE_CANVAS_BUILDS_PER_TEAM,
    record_publish,
    upload_source_project,
)
from posthog.api.file_system.canvas_source import (
    CANVAS_SDK_VERSION,
    extract_legacy_code,
    has_errors,
    synthetic_source_project,
    validate_source_project,
)
from posthog.api.file_system.deletion import (
    HOG_FUNCTION_TYPES,
    delete_file_system_object,
    is_file_system_type_registered,
    undo_delete as undo_delete_object,
)
from posthog.api.file_system.file_system_logging import log_api_file_system_view
from posthog.api.file_system.folder_context_generation import (
    ContextGenerationSerializer,
    ContextGenerationSetSerializer,
)
from posthog.api.file_system.folder_context_generation_service import (
    get_context_generation_task_id,
    set_context_generation_task_id,
)
from posthog.api.file_system.folder_instructions import (
    FolderInstructionsPublishSerializer,
    FolderInstructionsSerializer,
    FolderInstructionsVersionSerializer,
)
from posthog.api.file_system.folder_instructions_service import (
    FolderInstructionsVersionConflictError,
    FolderInstructionsVersionLimitError,
    delete_folder_instructions,
    ensure_blank_folder_instructions,
    get_folder_instructions_versions,
    get_latest_folder_instructions,
    publish_folder_instructions,
)
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.auth import OAuthAccessTokenAuthentication
from posthog.decorators import disallow_if_impersonated
from posthog.models.file_system.canvas_build import CanvasBuild
from posthog.models.file_system.file_system import (
    DEFAULT_SURFACE,
    FileSystem,
    create_or_update_file,
    join_path,
    split_path,
    surface_q,
)
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.file_system.file_system_view_log import get_recent_file_system_items, recent_view_logs
from posthog.models.file_system.unfiled_file_saver import save_unfiled_files
from posthog.models.team import Team
from posthog.models.user import User
from posthog.storage.object_storage import ObjectStorageError
from posthog.temporal.oauth import SANDBOX_OAUTH_APP_CLIENT_IDS
from posthog.utils import str_to_bool

from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

DELETE_PREVIEW_ENTRY_LIMIT = 200

# Search-within-Recents scans this many of the user's most-recent views, then the text filter trims
# them to a page. Bounds the hydration key set so the query stays cheap on heavy view-log histories.
RECENTS_SEARCH_SCAN_LIMIT = 200


class FileSystemSerializer(FileSystemAccessLevelSerializerMixin, serializers.ModelSerializer):
    last_viewed_at = serializers.DateTimeField(read_only=True, allow_null=True)
    created_by = UserBasicSerializer(read_only=True, allow_null=True)

    class Meta:
        model = FileSystem
        fields = [
            "id",
            "path",
            "depth",
            "type",
            "ref",
            "href",
            "meta",
            "shortcut",
            "created_at",
            "created_by",
            "last_viewed_at",
            "user_access_level",
        ]
        read_only_fields = [
            "id",
            "depth",
            "created_at",
            "team_id",
            "last_viewed_at",
            "user_access_level",
        ]

    def update(self, instance: FileSystem, validated_data: dict[str, Any]) -> FileSystem:
        if "path" in validated_data:
            instance.depth = len(split_path(validated_data["path"]))
        return super().update(instance, validated_data)

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> FileSystem:
        request = self.context["request"]
        team = self.context["get_team"]()
        surface = self.context.get("file_system_surface", DEFAULT_SURFACE)

        full_path = validated_data["path"]
        segments = split_path(full_path)

        for depth_index in range(1, len(segments)):
            parent_path = "/".join(segments[:depth_index])
            folder_exists = FileSystem.objects.filter(surface_q(surface), team=team, path=parent_path).exists()
            if not folder_exists:
                FileSystem.objects.create(
                    team=team,
                    path=parent_path,
                    depth=depth_index,
                    type="folder",
                    created_by=request.user,
                    shortcut=False,
                    surface=surface,
                )

        if validated_data.get("shortcut") is None:
            validated_data["shortcut"] = False

        depth = len(segments)
        file_system = FileSystem.objects.create(
            team=team,
            created_by=request.user,
            depth=depth,
            surface=surface,
            **validated_data,
        )

        return file_system


class FileSystemsLimitOffsetPagination(pagination.LimitOffsetPagination):
    default_limit = 100


class UnfiledFilesQuerySerializer(serializers.Serializer):
    type = serializers.CharField(required=False, allow_blank=True)


class FileSystemViewLogSerializer(serializers.Serializer):
    type = serializers.CharField()
    ref = serializers.CharField()
    viewed_at = serializers.DateTimeField(required=False)


class FileSystemViewLogListQuerySerializer(serializers.Serializer):
    type = serializers.CharField(required=False, allow_blank=True)
    limit = serializers.IntegerField(required=False, min_value=1)


class UndoDeleteItemSerializer(serializers.Serializer):
    type = serializers.CharField()
    ref = serializers.CharField()
    path = serializers.CharField(required=False, allow_blank=True)


class UndoDeleteRequestSerializer(serializers.Serializer):
    items = UndoDeleteItemSerializer(many=True)


def tokenize_search(search: str) -> list[str]:
    """Tokenize the search query while tolerating unmatched single quotes."""

    def _build_lexer(allow_single_quotes: bool) -> shlex.shlex:
        lexer = shlex.shlex(search, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        if not allow_single_quotes:
            lexer.quotes = '"'
            if "'" not in lexer.wordchars:
                lexer.wordchars += "'"
        return lexer

    try:
        return list(_build_lexer(allow_single_quotes=True))
    except ValueError:
        try:
            return list(_build_lexer(allow_single_quotes=False))
        except ValueError:
            return search.split()


@extend_schema(extensions={"x-product": "core"})
class FileSystemViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "file_system"
    queryset = FileSystem.objects.select_related("created_by")
    serializer_class = FileSystemSerializer
    filter_backends = [filters.SearchFilter]
    pagination_class = FileSystemsLimitOffsetPagination
    # Product surface this tree serves. Subclass and override to expose a different surface
    # (e.g. "desktop") on its own route. The default surface also matches legacy NULL rows.
    file_system_surface: str = DEFAULT_SURFACE
    # GET /instructions/ and /instructions/versions/ are reads; PUT/PATCH/DELETE on
    # /instructions/ resolve to `publish_instructions` / `delete_instructions` via DRF's
    # method mapping, so they go in the write bucket.
    scope_object_read_actions = [
        "list",
        "retrieve",
        "instructions",
        "instructions_versions",
        "unfiled",
        "count",
        "count_by_path",
        "context_generation",
        "canvases",
        "canvas_source",
        "canvas_builds",
        # POST, but side-effect free: it only reports diagnostics.
        "canvas_validate",
    ]
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "publish_instructions",
        "delete_instructions",
        "move",
        "link",
        "log_view",
        "undo_delete",
        "set_context_generation",
        "publish_canvas",
        "create_canvas",
        "publish_canvas_source",
        "edit_canvas_source",
    ]

    def _basename_regex(self, value: str) -> str:
        return rf"(^|(?<!\\)/)([^/]|\\.)*{re.escape(value)}([^/]|\\.)*$"

    def _apply_search_to_queryset(self, queryset: QuerySet, search: str, *, basename_only: bool = False) -> QuerySet:
        """
        Supported token formats
        -----------------------
        • <field>:<value>      → field-specific search
            • path:<txt>     → match any parent-folder segment (substring)
            • name:<txt>     → match the basename (substring)
            • user:<txt>     → matches creator full-name or e-mail (use **user:me** as a shortcut)
            • type:<txt>     → exact match (or use an ending “/” for prefix match)
            • ref:<txt>      → exact match
        • Plain tokens         → searched in `path` (`icontains`)
        • Quotes               → `"multi word value"` keeps spaces together
        • Negation             → prefix any token with `-` or `!` (e.g. `-type:folder`, `-report`)
        • All positive/negative tokens are **AND-combined**.

        Example
        -------
        search='name:report type:file -author:"Paul D" draft'
        """
        tokens = tokenize_search(search)
        if not tokens:
            return queryset

        combined_q: Q = Q()  # neutral element for "&" chaining

        for raw in tokens:
            negated = raw.startswith(("-", "!"))
            token = raw[1:] if negated else raw

            if (token.startswith('"') and token.endswith('"')) or (token.startswith("'") and token.endswith("'")):
                token = token[1:-1]

            if not token:
                continue

            # field-qualified token?
            if ":" in token:
                field, value = token.split(":", 1)
                field = field.lower()
                value = value.strip()
                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]

                if field == "path":
                    # ────────────────────────────────────────────────────────────
                    # substring search in ANY *parent* segment (everything before
                    # the last segment).  We look for a segment that *contains*
                    # the value, bounded by un-escaped slashes.
                    #
                    #   (^|(?<!\\)/)       ← segment start (BOL or un-escaped /)
                    #   ([^/]|\\.)*value([^/]|\\.)*
                    #   (?<!\\)/          ← next un-escaped slash (ensures “parent”)
                    # ────────────────────────────────────────────────────────────
                    regex = rf"(^|(?<!\\)/)([^/]|\\.)*{re.escape(value)}([^/]|\\.)*(?<!\\)/"
                    q = Q(path__iregex=regex)

                elif field == "name":
                    # ────────────────────────────────────────────────────────────
                    # substring search *only* in the last segment (basename)
                    #   (^|(?<!\\)/)       ← segment start
                    #   ([^/]|\\.)*value([^/]|\\.)*
                    #   $                 ← end-of-string  (marks “last” segment)
                    # ────────────────────────────────────────────────────────────
                    q = Q(path__iregex=self._basename_regex(value))

                elif field in ("user", "author"):
                    #  user:me  → files created by the current user
                    if value.lower() == "me" and self.request.user.is_authenticated:
                        q = Q(created_by=self.request.user)
                    else:
                        # build “first last” once and do a single icontains
                        queryset = queryset.annotate(
                            _created_by_full_name=Concat(
                                F("created_by__first_name"),
                                Value(" "),
                                F("created_by__last_name"),
                            )
                        )
                        q = Q(_created_by_full_name__icontains=value) | Q(created_by__email__icontains=value)

                elif field == "type":
                    if value.endswith("/"):
                        q = Q(type__startswith=value)
                    elif value in HOG_FUNCTION_TYPES:
                        q = Q(type="hog_function/" + value)
                    else:
                        q = Q(type=value)
                elif field == "ref":
                    q = Q(ref=value)
                else:  # unknown prefix → search for the full token in path and type
                    q = Q(path__icontains=token) | Q(type__icontains=token)
            elif "/" in token and not basename_only:
                # ────────────────────────────────────────────────────────────
                # Plain free-text token
                #
                # If the token itself contains “/”, it may refer either to
                # a *real* path separator **or** to an escaped slash (\/)
                # that lives inside a single segment.  To support both cases
                # we build a case-insensitive REGEX where every “/” becomes
                # the alternation   ( "/" | "\/" ).
                #
                # token:   "go/revenue"
                # regex:   r"go(?:/|\\/ )revenue"
                # ────────────────────────────────────────────────────────────
                sep_pattern = r"(?:/|\\/)"
                regex = sep_pattern.join(re.escape(part) for part in token.split("/"))
                q = Q(path__iregex=regex) | Q(type__iregex=regex)
            else:
                if basename_only:
                    q = Q(path__iregex=self._basename_regex(token))
                else:
                    # plain free-text token: search in path or type
                    q = Q(path__icontains=token) | Q(type__icontains=token)

            combined_q &= ~q if negated else q

        return queryset.filter(combined_q)

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["file_system_surface"] = self.file_system_surface
        return context

    def _scope_by_project(self, queryset: QuerySet) -> QuerySet:
        """
        Show all objects belonging to the project, restricted to this viewset's surface.
        """
        return queryset.filter(surface_q(self.file_system_surface), team__project_id=self.team.project_id)

    def _scope_by_project_and_environment(self, queryset: QuerySet) -> QuerySet:
        """
        Show all objects belonging to the project, except for hog functions, which are scoped by team.
        """
        queryset = self._scope_by_project(queryset)
        # type !~ 'hog_function/.*' or team = $current
        queryset = queryset.filter(Q(**self.parent_query_kwargs) | ~Q(type__startswith="hog_function/"))
        return queryset

    def _filter_queryset_by_parents_lookups(self, queryset):
        return self._scope_by_project(queryset)

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = self._scope_by_project_and_environment(queryset)

        depth_param = self.request.query_params.get("depth")
        parent_param = self.request.query_params.get("parent")
        path_param = self.request.query_params.get("path")
        type_param = self.request.query_params.get("type")
        not_type_param = self.request.query_params.get("not_type")
        type__startswith_param = self.request.query_params.get("type__startswith")
        ref_param = self.request.query_params.get("ref")
        order_by_param = self.request.query_params.get("order_by")
        created_at__gt = self.request.query_params.get("created_at__gt")
        created_at__lt = self.request.query_params.get("created_at__lt")
        search_param = self.request.query_params.get("search")
        search_name_only = str_to_bool(self.request.query_params.get("search_name_only"))

        if depth_param is not None:
            try:
                depth_value = int(depth_param)
                queryset = queryset.filter(depth=depth_value)
            except ValueError:
                pass
        if path_param:
            queryset = queryset.filter(path=path_param)
        if parent_param:
            queryset = queryset.filter(path__startswith=f"{parent_param}/")
        if type_param:
            queryset = queryset.filter(type=type_param)
        if not_type_param:
            queryset = queryset.exclude(type=not_type_param)
        if type__startswith_param:
            queryset = queryset.filter(type__startswith=type__startswith_param)
        if created_at__gt:
            queryset = queryset.filter(created_at__gt=created_at__gt)
        if created_at__lt:
            queryset = queryset.filter(created_at__lt=created_at__lt)
        if search_param:
            queryset = self._apply_search_to_queryset(queryset, search_param, basename_only=search_name_only)

        if self.user_access_control:
            queryset = self.user_access_control.filter_and_annotate_file_system_queryset(queryset)

        if ref_param:
            queryset = queryset.filter(ref=ref_param)
            queryset = queryset.order_by("shortcut")  # override order
        elif order_by_param:
            if order_by_param in ["path", "-path", "created_at", "-created_at"]:
                queryset = queryset.order_by(order_by_param)
            else:
                # `last_viewed_at` ordering (Recents, with or without a search term) is served
                # view-log-first in `_list_recents`, so it never reaches this queryset path.
                queryset = queryset.order_by("-created_at")
        elif self.action == "list":
            if depth_param is not None:
                queryset = queryset.order_by(
                    Case(
                        When(type="folder", then=Value(0)),
                        default=Value(1),
                        output_field=IntegerField(),
                    ),
                    Lower("path"),
                )
            else:
                queryset = queryset.order_by(Lower("path"))

        return queryset

    def list(self, request, *args, **kwargs):
        order_by_param = request.query_params.get("order_by")
        # Recents (the high-volume, timeout-prone path) is served view-log-first, with or without a
        # search term — one query function, no join, no COUNT(*).
        if order_by_param in ("-last_viewed_at", "last_viewed_at") and request.user.is_authenticated:
            return self._list_recents(request, descending=order_by_param == "-last_viewed_at")

        response = super().list(request, *args, **kwargs)
        response.data["users"] = self._created_by_users(response.data.get("results", []))
        return response

    def _created_by_users(self, results: builtins.list[dict[str, Any]]) -> builtins.list[dict[str, Any]]:
        # Collect user IDs from the "created_by" meta field so the client can render avatars
        # without a second round-trip.
        user_ids = {
            created_by
            for item in results
            if isinstance((created_by := item.get("meta", {}).get("created_by")), int) and created_by
        }
        if not user_ids:
            return []
        users_qs = User.objects.filter(organization=self.organization, id__in=user_ids).distinct()
        return cast(builtins.list[dict[str, Any]], UserBasicSerializer(users_qs, many=True).data)

    def _list_recents(self, request: Request, *, descending: bool) -> Response:
        """Serve the Recents widget view-log-first (see `get_recent_file_system_items`).

        Avoids both the un-indexable sort on a joined column and the pagination `COUNT(*)` — the
        widget only ever needs the first page, so we return the rows directly. A `search` term just
        filters the hydration: we scan a wider window of recent views and let the text filter trim
        it, so search-within-Recents shares the exact same query path.

        Only the params the Recents callers actually send are honoured here: `limit`, `not_type`,
        `search` (+ `search_name_only`). The other list filters (`parent`, `type`, `depth`, `ref`,
        `type__startswith`, `created_at__*`) are intentionally not applied on this path — nothing
        pairs them with `last_viewed_at` ordering. Add handling here if a caller ever needs to.
        """
        try:
            limit = int(request.query_params.get("limit", FileSystemsLimitOffsetPagination.default_limit))
        except (TypeError, ValueError):
            limit = FileSystemsLimitOffsetPagination.default_limit
        limit = max(1, min(limit, 1000))

        not_type_param = request.query_params.get("not_type")
        exclude_types = [not_type_param] if not_type_param else None
        search_param = request.query_params.get("search")

        base_queryset = FileSystem.objects.filter(surface_q(self.file_system_surface), team_id=self.team.id)
        if self.user_access_control:
            base_queryset = self.user_access_control.filter_and_annotate_file_system_queryset(base_queryset)
        if search_param:
            base_queryset = self._apply_search_to_queryset(
                base_queryset, search_param, basename_only=str_to_bool(request.query_params.get("search_name_only"))
            )

        items = get_recent_file_system_items(
            team_id=self.team.id,
            user_id=cast(User, request.user).id,
            surface=self.file_system_surface,
            # When searching, the text filter does the narrowing, so scan a wider recency window.
            limit=RECENTS_SEARCH_SCAN_LIMIT if search_param else limit,
            exclude_types=exclude_types,
            file_system_queryset=base_queryset,
            descending=descending,
        )
        # Ordering is handled at the view-log query level, so a search scan that widened the window
        # is the only reason to re-slice here — `descending` already picked the right end.
        items = items[:limit]

        results = self.get_serializer(items, many=True).data
        return Response(
            {
                "count": len(results),
                "next": None,
                "previous": None,
                "results": results,
                "users": self._created_by_users(results),
            }
        )

    def _allow_delete_without_ref(self, entry: FileSystem) -> bool:
        """Whether a registered-type row with no ref may be deleted as a bare row.

        On the web surface every registered row references a real object, so a
        ref-less row is a data-integrity error we refuse to delete. Surfaces where
        registered types can legitimately be ref-less (desktop canvases store their
        source in `meta`, not a backing Dashboard) override this to allow it.
        """
        return False

    def _ensure_can_delete(self, entry: FileSystem) -> None:
        stack: list[FileSystem] = [entry]
        seen: set[str] = set()
        entries_to_check: list[FileSystem] = []

        while stack:
            current = stack.pop()
            key = f"{current.id}"
            if key in seen:
                continue
            seen.add(key)

            if current.shortcut:
                continue

            if current.type == "folder":
                descendants = FileSystem.objects.filter(path__startswith=f"{current.path}/")
                descendants = self._scope_by_project_and_environment(descendants)
                if self.user_access_control:
                    descendants = self.user_access_control.filter_and_annotate_file_system_queryset(descendants)
                stack.extend(descendants)
                continue

            entries_to_check.append(current)

        if not entries_to_check:
            return None

        ids_to_remove = [entry.id for entry in entries_to_check]

        for current in entries_to_check:
            remaining = (
                FileSystem.objects.filter(team=current.team, type=current.type, ref=current.ref, shortcut=False)
                .exclude(id__in=ids_to_remove)
                .count()
            )

            if not is_file_system_type_registered(current.type):
                continue

            if remaining == 0 and not current.ref and not self._allow_delete_without_ref(current):
                raise serializers.ValidationError(
                    {"detail": f"Cannot delete type '{current.type}' without a reference."}
                )

        return None

    def _delete_file_system_entry(self, entry: FileSystem) -> builtins.list[dict[str, Any]]:
        deleted_objects: list[dict[str, Any]] = []

        if entry.shortcut:
            entry.delete()
            return deleted_objects

        if entry.type == "folder":
            descendants = FileSystem.objects.filter(path__startswith=f"{entry.path}/")
            descendants = self._scope_by_project_and_environment(descendants)
            if self.user_access_control:
                descendants = self.user_access_control.filter_and_annotate_file_system_queryset(descendants)
            for child in descendants.order_by("depth", "path"):
                deleted_objects.extend(self._delete_file_system_entry(child))
            entry.delete()
            return deleted_objects

        remaining = (
            FileSystem.objects.filter(team=entry.team, type=entry.type, ref=entry.ref, shortcut=False)
            .exclude(id=entry.id)
            .count()
        )

        if not is_file_system_type_registered(entry.type):
            raise serializers.ValidationError({"detail": f"Cannot delete resources with type '{entry.type}'."})

        if remaining > 0:
            entry.delete()
            return deleted_objects

        if not entry.ref:
            if self._allow_delete_without_ref(entry):
                entry.delete()
                return deleted_objects
            raise serializers.ValidationError({"detail": f"Cannot delete type '{entry.type}' without a reference."})

        entry_path = entry.path
        result = delete_file_system_object(
            entry,
            user=self.request.user,
            request=self.request,
            team=self.team,
            organization=getattr(self, "organization", None),
        )

        deleted_objects.append(
            {
                "type": result.type,
                "ref": result.ref,
                "mode": result.mode,
                "undo": result.undo,
                "path": entry_path,
                "can_undo": result.can_undo and bool(result.ref),
            }
        )
        return deleted_objects

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        original_path = instance.path
        instance_created_by = instance.created_by
        deleted_objects: list[dict[str, Any]]

        with transaction.atomic():
            self._ensure_can_delete(instance)
            deleted_objects = self._delete_file_system_entry(instance)

        if instance.type == "folder":
            leftovers = self._scope_by_project(FileSystem.objects.filter(path__startswith=f"{original_path}/"))
            first_leftover = leftovers.first()
            if first_leftover:
                created_by = first_leftover.created_by or instance_created_by or cast(User, self.request.user)
                self._assure_parent_folders(first_leftover.path, created_by, first_leftover.team)

        if deleted_objects:
            return Response({"deleted": deleted_objects}, status=status.HTTP_200_OK)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["POST"], detail=False)
    def undo_delete(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = UndoDeleteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        items = serializer.validated_data["items"]
        undo_results: list[dict[str, str]] = []

        with transaction.atomic():
            for item in items:
                try:
                    restored_instance = undo_delete_object(
                        type_string=item["type"],
                        ref=item["ref"],
                        restore_path=item.get("path"),
                        user=request.user,
                        request=request,
                        team=self.team,
                        organization=getattr(self, "organization", None),
                    )
                except ValueError:
                    import logging

                    logging.exception(
                        "Exception during undo_delete_object (type=%s, ref=%s)", item.get("type"), item.get("ref")
                    )
                    raise serializers.ValidationError({"detail": "An internal error occurred during undo delete."})
                self._restore_file_system_path(restored_instance, item)
                undo_results.append({"type": item["type"], "ref": item["ref"]})

        return Response({"undone": undo_results}, status=status.HTTP_200_OK)

    @action(methods=["GET"], detail=False)
    def unfiled(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query_serializer = UnfiledFilesQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        file_type = query_serializer.validated_data.get("type")
        files = save_unfiled_files(self.team, cast(User, request.user), file_type, surface=self.file_system_surface)

        self._retroactively_fix_folders_and_depth(cast(User, request.user))

        if self.user_access_control:
            # nosemgrep: idor-lookup-without-team, idor-taint-user-input-to-model-get (IDs from prior team-scoped query)
            qs = FileSystem.objects.filter(id__in=[f.id for f in files])
            qs = self.user_access_control.filter_and_annotate_file_system_queryset(qs)
            file_count = qs.count()
        else:
            file_count = len(files)

        return Response(
            {
                "count": file_count,
            },
            status=status.HTTP_200_OK,
        )

    @action(methods=["POST"], detail=True)
    def move(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        old_path = instance.path
        new_path = request.data.get("new_path")
        if not new_path:
            return Response({"detail": "new_path is required"}, status=status.HTTP_400_BAD_REQUEST)

        self._assure_parent_folders(new_path, cast(User, request.user))

        if instance.type == "folder":
            if new_path == instance.path:
                return Response({"detail": "Cannot move folder into itself"}, status=status.HTTP_400_BAD_REQUEST)

            with transaction.atomic():
                qs = FileSystem.objects.filter(path__startswith=f"{instance.path}/")
                qs = self._scope_by_project_and_environment(qs)
                if self.user_access_control:
                    qs = self.user_access_control.filter_and_annotate_file_system_queryset(qs)
                for file in qs:
                    file.path = new_path + file.path[len(instance.path) :]
                    file.depth = len(split_path(file.path))
                    file.save()

                targets = FileSystem.objects.filter(path=new_path).all()
                targets = self._scope_by_project_and_environment(targets)
                # We're a folder, and we're moving into a folder with the same name. Delete one.
                if any(target.type == "folder" for target in targets):
                    # TODO: merge access controls once those are in place
                    instance.delete()
                else:
                    instance.path = new_path
                    instance.depth = len(split_path(instance.path))
                    instance.save()

        else:
            instance.path = new_path
            instance.depth = len(split_path(instance.path))
            instance.save()

        # Repair folder tree for items we *didn't* move (hog functions in other teams under the moved folder)
        leftovers = self._scope_by_project(FileSystem.objects.filter(path__startswith=f"{old_path}/"))
        first_leftover = leftovers.first()
        if first_leftover:
            self._assure_parent_folders(first_leftover.path, instance.created_by, first_leftover.team)

        return Response(
            FileSystemSerializer(instance).data,
            status=status.HTTP_200_OK,
        )

    @action(methods=["POST"], detail=True)
    def link(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        new_path = request.data.get("new_path")
        if not new_path:
            return Response({"detail": "new_path is required"}, status=status.HTTP_400_BAD_REQUEST)

        self._assure_parent_folders(new_path, cast(User, request.user))

        if instance.type == "folder":
            if new_path == instance.path:
                return Response({"detail": "Cannot link folder into itself"}, status=status.HTTP_400_BAD_REQUEST)

            with transaction.atomic():
                qs = FileSystem.objects.filter(path__startswith=f"{instance.path}/")
                qs = self._scope_by_project_and_environment(qs)
                if self.user_access_control:
                    qs = self.user_access_control.filter_and_annotate_file_system_queryset(qs)

                for file in qs:
                    file.pk = None  # This removes the id
                    file.path = new_path + file.path[len(instance.path) :]
                    file.depth = len(split_path(file.path))
                    file.shortcut = True
                    file.save()  # A new instance is created with a new id

                targets_q = FileSystem.objects.filter(path=new_path)
                targets_q = self._scope_by_project_and_environment(targets_q)
                targets = targets_q.all()
                if any(target.type == "folder" for target in targets):
                    # We're a folder, and we're link into a folder with the same name. Noop.
                    pass
                else:
                    instance.pk = None  # This removes the id
                    instance.path = new_path
                    instance.depth = len(split_path(instance.path))
                    instance.shortcut = True
                    instance.save()  # A new instance is created with a new id

        else:
            instance.pk = None  # This removes the id
            instance.path = new_path + instance.path[len(instance.path) :]
            instance.depth = len(split_path(instance.path))
            instance.shortcut = True
            instance.save()  # A new instance is created with a new id

        return Response(
            FileSystemSerializer(instance).data,
            status=status.HTTP_200_OK,
        )

    @action(methods=["POST"], detail=True)
    def count(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Get count of all files in a folder."""
        instance = self.get_object()
        if instance.type != "folder":
            return Response({"detail": "Count can only be called on folders"}, status=status.HTTP_400_BAD_REQUEST)

        qs = FileSystem.objects.filter(path__startswith=f"{instance.path}/").order_by("depth", "path")
        qs = self._scope_by_project_and_environment(qs)
        if self.user_access_control:
            qs = self.user_access_control.filter_and_annotate_file_system_queryset(qs)

        total_count = qs.count()
        preview_entries = list(qs[:DELETE_PREVIEW_ENTRY_LIMIT])
        serializer = self.get_serializer(preview_entries, many=True)

        return Response(
            {
                "count": total_count,
                "entries": serializer.data,
                "has_more": total_count > len(preview_entries),
            },
            status=status.HTTP_200_OK,
        )

    @action(methods=["GET", "POST"], detail=False, url_path="log_view")
    @disallow_if_impersonated(message="Impersonated sessions cannot log file system views.", allowed_methods=["GET"])
    def log_view(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if request.method == "GET":
            return self._list_log_views(request)

        serializer = FileSystemViewLogSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        representation = FileSystemRepresentation(
            base_folder="",
            type=data["type"],
            ref=data["ref"],
            name="",
            href="",
            meta={},
            surface=self.file_system_surface,
        )

        log_api_file_system_view(
            request,
            representation,
            team_id=self.team.id,
            viewed_at=data.get("viewed_at"),
        )

        return Response(status=status.HTTP_204_NO_CONTENT)

    def _list_log_views(self, request: Request) -> Response:
        if not request.user.is_authenticated:
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        serializer = FileSystemViewLogListQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        validated = serializer.validated_data

        queryset = recent_view_logs(
            team_id=self.team.id,
            user_id=request.user.id,
            surface=self.file_system_surface,
            type=validated.get("type") or None,
            limit=validated.get("limit"),
        )

        return Response(FileSystemViewLogSerializer(queryset, many=True).data)

    @action(methods=["POST"], detail=False)
    def count_by_path(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Get count of all files in a folder."""
        path_param = self.request.query_params.get("path")
        if not path_param:
            return Response({"detail": "path parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        qs = FileSystem.objects.filter(path__startswith=f"{path_param}/").order_by("depth", "path")
        qs = self._scope_by_project_and_environment(qs)
        if self.user_access_control:
            qs = self.user_access_control.filter_and_annotate_file_system_queryset(qs)

        total_count = qs.count()
        preview_entries = list(qs[:DELETE_PREVIEW_ENTRY_LIMIT])
        serializer = self.get_serializer(preview_entries, many=True)

        return Response(
            {
                "count": total_count,
                "entries": serializer.data,
                "has_more": total_count > len(preview_entries),
            },
            status=status.HTTP_200_OK,
        )

    def _assure_parent_folders(self, path: str, created_by: User, team: Team | None = None) -> None:
        """
        Ensure that all parent folders for the given path exist for the provided team.
        For example, if the path is "a/b/c/d", this will ensure that "a", "a/b", and "a/b/c"
        all exist as folder type FileSystem entries.
        """
        segments = split_path(path)
        for depth_index in range(1, len(segments)):
            parent_path = join_path(segments[:depth_index])
            parent_q = FileSystem.objects.filter(path=parent_path)
            parent_q = self._scope_by_project(parent_q)
            if not parent_q.exists():
                FileSystem.objects.create(
                    team=team or self.team,
                    path=parent_path,
                    depth=depth_index,
                    type="folder",
                    created_by=created_by,
                    surface=self.file_system_surface,
                )

    def _restore_file_system_path(self, instance: Any, payload: dict[str, Any]) -> None:
        restore_path = payload.get("path")
        if restore_path is None:
            return

        team = getattr(instance, "team", None) if instance is not None else None
        team = team or self.team

        created_by = getattr(instance, "created_by", None) if instance is not None else None
        request_user = self.request.user if isinstance(self.request.user, User) else None
        created_by_user = created_by if isinstance(created_by, User) else request_user
        if created_by_user is None:
            return

        self._assure_parent_folders(restore_path, created_by_user, team)

        update_count = FileSystem.objects.filter(
            surface_q(self.file_system_surface), team=team, type=payload["type"], ref=payload["ref"]
        ).update(
            path=restore_path,
            depth=len(split_path(restore_path)),
        )

        if update_count == 0 and hasattr(instance, "get_file_system_representation"):
            fs_data: FileSystemRepresentation = instance.get_file_system_representation()
            segments = split_path(restore_path)
            folder_path = "/".join(segments[:-1]) if len(segments) > 1 else ""
            name = segments[-1] if segments else fs_data.name
            create_or_update_file(
                team=team,
                base_folder=folder_path or fs_data.base_folder,
                name=name,
                file_type=fs_data.type,
                ref=fs_data.ref,
                href=fs_data.href,
                meta=fs_data.meta,
                created_at=fs_data.meta.get("created_at"),
                created_by_id=fs_data.meta.get("created_by"),
                surface=self.file_system_surface,
            )

    def _retroactively_fix_folders_and_depth(self, user: User) -> None:
        """
        For all existing FileSystem rows in `team`, ensure that any missing parent
        folders are created. Also ensure `depth` is correct.
        """

        # TODO: this needs some concurrency controls or a unique index
        scoped_files = self._scope_by_project_and_environment(FileSystem.objects.all())
        existing_paths = set(scoped_files.values_list("path", flat=True))

        folders_to_create = []
        items_to_update = []

        all_files = scoped_files.select_related("created_by")
        for file_obj in all_files:
            segments = split_path(file_obj.path)
            correct_depth = len(segments)

            # If depth is missing or incorrect, fix it
            if file_obj.depth != correct_depth:
                file_obj.depth = correct_depth
                items_to_update.append(file_obj)

            # Create missing parent folders
            # e.g. for path "a/b/c/d/e", the parent folders are:
            #  "a" (depth=1), "a/b" (depth=2), "a/b/c" (depth=3), "a/b/c/d" (depth=4)
            for depth_index in range(1, len(segments)):
                parent_path = join_path(segments[:depth_index])
                if parent_path not in existing_paths:
                    # Mark that we have it now (so we don't create duplicates)
                    existing_paths.add(parent_path)
                    folders_to_create.append(
                        FileSystem(
                            team=self.team,
                            path=parent_path,
                            depth=depth_index,
                            type="folder",
                            created_by=user,
                            surface=self.file_system_surface,
                        )
                    )

        if folders_to_create:
            FileSystem.objects.bulk_create(folders_to_create)

        if items_to_update:
            for item in items_to_update:
                item.save()


class CanvasPublishConflictSerializer(serializers.Serializer):
    """409 body for a guarded canvas publish based on a stale version."""

    detail = serializers.CharField(help_text="Human-readable description of the conflict and how to recover.")
    code = serializers.CharField(help_text='Always "version_conflict".')
    current_version_id = serializers.CharField(
        allow_null=True,
        help_text="The canvas's live currentVersionId at rejection time (null when the canvas has no versions).",
    )


class CanvasSourceAssetSerializer(serializers.Serializer):
    encoding = serializers.ChoiceField(choices=["base64"])
    contentType = serializers.ChoiceField(
        choices=[
            "image/png",
            "image/jpeg",
            "image/gif",
            "image/webp",
            "image/svg+xml",
            "font/woff",
            "font/woff2",
            "application/wasm",
            "application/octet-stream",
        ]
    )
    content = serializers.RegexField(
        regex=r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$",
        max_length=2_796_204,
    )


class CanvasPostHogCapabilitiesSerializer(serializers.Serializer):
    insights = serializers.ListField(child=serializers.CharField(max_length=128), max_length=100)
    inlineQueries = serializers.BooleanField()
    captureEvents = serializers.ListField(child=serializers.CharField(max_length=200), max_length=100)


class CanvasNetworkCapabilitiesSerializer(serializers.Serializer):
    origins = serializers.ListField(child=serializers.URLField(max_length=2048), max_length=20)


class CanvasCapabilitiesSerializer(serializers.Serializer):
    posthog = CanvasPostHogCapabilitiesSerializer()
    network = CanvasNetworkCapabilitiesSerializer()


class CanvasSourceProjectSerializer(serializers.Serializer):
    """A canvas's multi-file source project — the canonical write format for canvas source.

    Until the canvas build service ships, projects are constrained to the
    legacy-compatible shape: `index.html` (a fixed synthetic shell) plus
    `src/canvas.tsx` (the single React component the runtime mounts).
    """

    schemaVersion = serializers.IntegerField(
        help_text="Source-project schema version. Currently always 1.",
    )
    files = serializers.DictField(
        child=serializers.CharField(allow_blank=True, trim_whitespace=False),
        help_text=(
            "Project files keyed by relative path (forward slashes, no '..'). Until the canvas build "
            'service ships, only "index.html" and "src/canvas.tsx" (the single React component the '
            "canvas mounts) are supported."
        ),
    )
    assets = serializers.DictField(
        child=CanvasSourceAssetSerializer(),
        required=False,
        default=dict,
        help_text="Optional base64-encoded binary assets keyed by safe project-relative paths.",
    )
    entryHtml = serializers.CharField(
        help_text='The project\'s entry HTML file. Currently always "index.html".',
    )
    dependencies = serializers.DictField(
        child=serializers.CharField(),
        required=False,
        default=dict,
        help_text=(
            "Exact-version dependencies, restricted to the platform-supported set (react, react-dom, "
            "@posthog/quill, recharts, lucide-react, dayjs) at their pinned versions."
        ),
    )
    canvasSdkVersion = serializers.CharField(
        required=False,
        default=CANVAS_SDK_VERSION,
        help_text="Version of the host-injected `ph` canvas SDK the project targets.",
    )
    capabilities = CanvasCapabilitiesSerializer(
        required=False,
        default=lambda: {
            "posthog": {"insights": [], "inlineQueries": False, "captureEvents": []},
            "network": {"origins": []},
        },
        help_text="Bounded capabilities frozen into the built artifact.",
    )


class CanvasDiagnosticSerializer(serializers.Serializer):
    """One structured validation/build diagnostic for a canvas source project."""

    severity = serializers.ChoiceField(
        choices=["error", "warning"],
        help_text="'error' blocks publishing; 'warning' is advisory and does not block.",
    )
    code = serializers.CharField(
        help_text="Stable machine-readable diagnostic code, e.g. 'import_not_allowed' or 'unsupported_file'.",
    )
    message = serializers.CharField(help_text="Human-readable description of the problem and how to fix it.")
    path = serializers.CharField(
        required=False,
        help_text="Project-relative path of the file the diagnostic points at, when file-specific.",
    )
    line = serializers.IntegerField(
        required=False,
        help_text="1-based line number within `path`, when the diagnostic points at a specific line.",
    )


class CanvasSummarySerializer(serializers.Serializer):
    """Identity and version pointers for one canvas (a desktop 'dashboard' entry)."""

    id = serializers.UUIDField(help_text="The canvas's desktop file-system id.")
    name = serializers.CharField(help_text="Display name of the canvas (the leaf segment of its path).")
    channel_id = serializers.CharField(
        allow_null=True,
        help_text="File-system id of the channel (folder) the canvas belongs to, when recorded.",
    )
    current_version_id = serializers.CharField(
        allow_null=True,
        help_text="Id of the live source version — pass as expected_current_version_id on publish. Null before the first publish.",
    )
    version_count = serializers.IntegerField(help_text="Number of source versions in the canvas's history.")
    created_at = serializers.DateTimeField(help_text="When the canvas was created.")
    current_source_version_id = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Id of the normalized source-version row the canvas's head points at (null before the lifecycle recorded one).",
    )
    published_build_id = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Id of the canvas's live (last successful, still-eligible) build. Null until a build completes.",
    )


class CanvasCreateSerializer(serializers.Serializer):
    """Payload for creating a new, empty canvas in a channel."""

    name = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
        help_text="Display name for the canvas. Slashes are replaced with spaces.",
    )
    channel_id = serializers.CharField(
        help_text="Desktop file-system id of the channel (folder) to create the canvas in.",
    )


class CanvasSourceResponseSerializer(serializers.Serializer):
    """A canvas's source project plus the version pointer edits must be based on."""

    canvas = CanvasSummarySerializer(help_text="Identity and version pointers for the canvas.")
    project = CanvasSourceProjectSerializer(
        help_text="The canvas's source project. Legacy single-file canvases are presented as a synthetic project."
    )
    current_version_id = serializers.CharField(
        allow_null=True,
        help_text="The live source version this project reflects — pass as expected_current_version_id when publishing an edit. Null before the first publish.",
    )


class CanvasValidateRequestSerializer(serializers.Serializer):
    """Payload for validating a candidate source project without publishing it."""

    project = CanvasSourceProjectSerializer(help_text="The candidate source project to validate.")


class CanvasValidateResponseSerializer(serializers.Serializer):
    """Validation outcome for a candidate source project."""

    valid = serializers.BooleanField(help_text="True when the project has no error-severity diagnostics.")
    diagnostics = CanvasDiagnosticSerializer(
        many=True,
        help_text="Structured diagnostics; errors block publishing, warnings are advisory.",
    )


class CanvasSourcePublishSerializer(serializers.Serializer):
    """Payload for publishing a complete canvas source project."""

    project = CanvasSourceProjectSerializer(help_text="The complete source project to publish.")
    prompt = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Short description of the change, stored on the appended version history entry.",
    )
    name = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        help_text="Optional new display name for the canvas (rewrites the leaf segment of its path).",
    )
    expected_current_version_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        help_text=(
            "Optimistic-concurrency guard: the current_version_id the publisher based its edits on "
            "(null when it read a canvas with no versions yet). When the canvas has since moved past it "
            "the publish is rejected with a 409 version_conflict instead of overwriting the newer head. "
            "Omit to publish unguarded."
        ),
    )


class CanvasSourceEditOperationSerializer(serializers.Serializer):
    """One per-file edit: set a file's content, or delete it."""

    path = serializers.CharField(
        help_text='Project-relative path of the file to write or delete (e.g. "src/canvas.tsx").'
    )
    content = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
        help_text="The file's complete new content. Null (or omitted) deletes the file.",
    )


class CanvasSourceEditSerializer(serializers.Serializer):
    """Payload for publishing per-file edits against the canvas's current source."""

    operations = CanvasSourceEditOperationSerializer(
        many=True,
        allow_empty=False,
        help_text="Edits applied in order to the canvas's current source project.",
    )
    prompt = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Short description of the change, stored on the appended version history entry.",
    )
    name = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        help_text="Optional new display name for the canvas (rewrites the leaf segment of its path).",
    )
    expected_current_version_id = serializers.CharField(
        allow_null=True,
        help_text=(
            "Required optimistic-concurrency guard: the current_version_id the edits are based on (null when the "
            "canvas has never been published). Diff edits against a moved head are rejected with 409 "
            "version_conflict — they cannot be published unguarded."
        ),
    )


class CanvasSourcePublishResponseSerializer(serializers.Serializer):
    """Result of a successful source-project publish."""

    canvas = CanvasSummarySerializer(help_text="The canvas after the publish, including the new version pointer.")
    current_version_id = serializers.CharField(help_text="Id of the source version this publish created.")
    diagnostics = CanvasDiagnosticSerializer(
        many=True,
        help_text="Advisory (warning-severity) diagnostics recorded for the published project.",
    )


class CanvasArtifactAssetSerializer(serializers.Serializer):
    """One emitted file of a built canvas artifact."""

    path = serializers.CharField(help_text="Artifact-relative path of the emitted file.")
    contentHash = serializers.CharField(help_text="Hex SHA-256 of the file content.")
    sizeBytes = serializers.IntegerField(help_text="Size of the file in bytes.")


class CanvasArtifactManifestSerializer(serializers.Serializer):
    """The manifest frozen into a ready build: entry, assets, versions, capabilities."""

    entryHtml = serializers.CharField(help_text="The artifact's entry HTML file.")
    assets = CanvasArtifactAssetSerializer(many=True, help_text="Every emitted artifact file with its content hash.")
    dependencies = serializers.DictField(
        child=serializers.CharField(),
        help_text="Exact dependency versions the artifact was built against.",
    )
    canvasSdkVersion = serializers.CharField(help_text="Version of the `ph` canvas SDK the artifact targets.")
    legacyComponentPath = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Path of the runtime-mounted React component, for legacy-tier artifacts.",
    )
    legacyCode = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
        help_text="The runtime-mounted component source, for legacy-tier artifacts.",
    )
    capabilities = serializers.DictField(
        help_text="Declared PostHog/network capabilities the artifact is held to at runtime.",
    )


class CanvasBuildSerializer(serializers.Serializer):
    """Lifecycle record of one build of a canvas source version."""

    id = serializers.UUIDField(help_text="The build's id.")
    source_version_id = serializers.UUIDField(help_text="The source version this build compiled.")
    build_status = serializers.ChoiceField(
        choices=["queued", "building", "ready", "failed"],
        help_text="Build lifecycle state. A failed build never replaces the last-known-good artifact.",
    )
    diagnostics = CanvasDiagnosticSerializer(
        many=True,
        help_text="Structured diagnostics recorded by the build (errors explain a failed status).",
    )
    manifest = CanvasArtifactManifestSerializer(
        required=False,
        allow_null=True,
        help_text="The frozen artifact manifest — present once the build is ready.",
    )
    integrity = serializers.CharField(
        allow_null=True,
        help_text="Hex SHA-256 over the manifest — the artifact's integrity anchor. Null until ready.",
    )
    artifact_url = serializers.URLField(
        allow_null=True,
        help_text="Short-lived URL for the ready build's entry HTML. Null until ready or when artifact delivery is unavailable.",
    )
    pinned = serializers.BooleanField(help_text="Pinned builds are retained for the lifetime of the canvas.")
    created_at = serializers.DateTimeField(help_text="When the build was queued.")
    finished_at = serializers.DateTimeField(allow_null=True, help_text="When the build reached a terminal state.")


class CanvasBuildsResponseSerializer(serializers.Serializer):
    """A canvas's build lifecycle: live pointers plus its most recent builds."""

    published_build_id = serializers.CharField(
        allow_null=True,
        help_text="Id of the canvas's live build (the last successful, still-eligible one). Null until a build completes.",
    )
    current_source_version_id = serializers.CharField(
        allow_null=True,
        help_text="Id of the source-version row the canvas's head points at.",
    )
    builds = CanvasBuildSerializer(many=True, help_text="Most recent builds, newest first (capped at 20).")


class CanvasBuildActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["retry", "pin", "unpin", "cancel"])
    build_id = serializers.UUIDField()


class CanvasSourceInvalidSerializer(serializers.Serializer):
    """400 body for a publish whose source project failed validation."""

    detail = serializers.CharField(help_text="Human-readable summary of why the project was rejected.")
    code = serializers.CharField(help_text='Always "invalid_source_project".')
    diagnostics = CanvasDiagnosticSerializer(
        many=True,
        help_text="The validation diagnostics, including at least one error.",
    )


@extend_schema(extensions={"x-product": "core"})
class DesktopFileSystemViewSet(FileSystemViewSet):
    """
    The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
    scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.

    Adds per-folder, versioned markdown instructions describing the contents of a folder.
    """

    file_system_surface = "desktop"

    def _scope_by_project(self, queryset: QuerySet) -> QuerySet:
        queryset = super()._scope_by_project(queryset)
        # Personal-space rows share the same path across users, so their creator
        # is the ownership boundary even when project-level access is shared.
        is_personal_space = Q(path="me") | Q(path__startswith="me/")
        return queryset.filter(~is_personal_space | Q(created_by=self.request.user))

    def _allow_delete_without_ref(self, entry: FileSystem) -> bool:
        # Desktop canvases are `dashboard`-typed rows whose source lives in `meta`,
        # not a backing Dashboard, so they legitimately have no ref. Delete the bare
        # row (nothing to cascade to) rather than refusing. Scope this to `dashboard`
        # only — any other registered type with no ref is still a data-integrity
        # error we refuse to delete, even on the desktop surface.
        return entry.type == "dashboard"

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        super().perform_create(serializer)
        instance = cast(FileSystem, serializer.instance)
        self._ensure_blank_instructions_for_created_path(instance)

    def _ensure_blank_instructions_for_created_path(self, instance: FileSystem) -> None:
        """Give every desktop folder along the created path a blank instruction set.

        Covers the created folder itself plus any parent folders auto-created by the serializer,
        so a "channel" always has instructions from the moment it exists.
        """
        segments = split_path(instance.path)
        candidate_paths = [join_path(segments[:depth_index]) for depth_index in range(1, len(segments))]
        if instance.type == "folder":
            candidate_paths.append(instance.path)
        if not candidate_paths:
            return

        folders = self._scope_by_project(FileSystem.objects.filter(path__in=candidate_paths, type="folder"))
        user = self.request.user if isinstance(self.request.user, User) else None
        for folder in folders:
            ensure_blank_folder_instructions(folder, user=user)

    def _get_folder_or_400(self) -> FileSystem | Response:
        instance = self.get_object()
        if instance.type != "folder":
            return Response(
                {"detail": "Instructions can only be attached to folders."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return instance

    def _get_dashboard_or_400(self) -> FileSystem | Response:
        instance = self.get_object()
        if instance.type != "dashboard":
            return Response(
                {"detail": "Canvas code can only be published to dashboards."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return instance

    def _apply_canvas_publish(
        self,
        dashboard: FileSystem,
        *,
        code: str,
        prompt: str | None,
        name: str | None,
        has_expected_version: bool,
        expected_version_id: str | None,
        record_lifecycle: Callable[[FileSystem, dict[str, Any], dict[str, Any]], None] | None = None,
    ) -> tuple[FileSystem, dict[str, Any] | None, bool]:
        """Append a canvas version and advance the pointer, under the row lock.

        Returns the (re-fetched) dashboard, a 409 `version_conflict` payload when a
        guarded publish is based on a stale version (the canvas is left untouched),
        and whether this was the canvas's first publish. `record_lifecycle` runs
        inside the transaction with the locked row, the merged meta, and the
        appended version entry — the hook the normalized source-version/build
        lifecycle uses so its rows commit or roll back with the publish.
        """
        now_ms = int(time.time() * 1000)
        version: dict[str, Any] = {"id": str(uuid4()), "code": code, "createdAt": now_ms}
        if prompt:
            version["prompt"] = prompt

        # Lock the row for the read-modify-write so concurrent publishes can't clobber
        # each other's appended version (each would otherwise build `versions` from the
        # same stale snapshot and the second write would drop the first).
        with transaction.atomic():
            dashboard = FileSystem.objects.select_for_update().get(pk=dashboard.pk)
            meta = dict(dashboard.meta or {})
            current_version_id = meta.get("currentVersionId")

            if has_expected_version and current_version_id != expected_version_id:
                conflict = {
                    "detail": "The canvas changed since it was read (a concurrent publish or an undo). "
                    "Re-fetch the canvas, re-apply the edits to the fresh source, and publish again.",
                    "code": "version_conflict",
                    "current_version_id": current_version_id,
                }
                return dashboard, conflict, False

            # Snapshot the live author context onto the version (reverting restores it).
            existing_context = meta.get("context")
            if isinstance(existing_context, str):
                version["context"] = existing_context
            versions = list(meta.get("versions") or [])
            first_publish = not versions and not meta.get("code")
            # Linear-discard: a publish always becomes the new head, so a redo tail past
            # the live pointer (left by an undo) is dropped rather than kept as
            # unreachable history — mirroring the client's undo/redo semantics.
            if current_version_id:
                pointer = next(
                    (
                        index
                        for index, existing in enumerate(versions)
                        if isinstance(existing, dict) and existing.get("id") == current_version_id
                    ),
                    None,
                )
                if pointer is not None:
                    versions = versions[: pointer + 1]
            versions.append(version)

            meta.update(
                {
                    "kind": "freeform",
                    "code": code,
                    "versions": versions,
                    "currentVersionId": version["id"],
                    "updatedAt": now_ms,
                }
            )
            if record_lifecycle is not None:
                record_lifecycle(dashboard, meta, version)
            dashboard.meta = meta

            update_fields = ["meta"]
            if name:
                # The canvas's display name is the leaf segment of its path; rename in place.
                segments = split_path(dashboard.path)
                segments[-1] = name
                dashboard.path = join_path(segments)
                dashboard.depth = len(segments)
                update_fields += ["path", "depth"]

            dashboard.save(update_fields=update_fields)

        return dashboard, None, first_publish

    def _resolve_channel(self, channel_id: str) -> FileSystem | None:
        """The project's channel folder with this id, or None (including a malformed id —
        agents pass arbitrary strings, and a UUID-field lookup on one raises)."""
        try:
            return self._scope_by_project(FileSystem.objects.all()).filter(id=channel_id, type="folder").first()
        except (ValueError, DjangoValidationError):
            return None

    def _canvas_summary(self, entry: FileSystem) -> dict[str, Any]:
        meta = entry.meta or {}
        segments = split_path(entry.path)
        return {
            "id": str(entry.id),
            "name": segments[-1] if segments else entry.path,
            "channel_id": meta.get("channelId"),
            "current_version_id": meta.get("currentVersionId"),
            "version_count": len(meta.get("versions") or []),
            "created_at": entry.created_at,
            "current_source_version_id": meta.get("currentSourceVersionId"),
            "published_build_id": meta.get("publishedBuildId"),
        }

    @extend_schema(
        operation_id="desktop_file_system_canvases_list",
        parameters=[
            OpenApiParameter(
                name="channel_id",
                type=str,
                required=False,
                description="Only return canvases inside this channel (desktop folder id).",
            ),
        ],
        responses={200: CanvasSummarySerializer(many=True)},
    )
    @action(methods=["GET"], detail=False, url_path="canvases", pagination_class=None, request=None)
    def canvases(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """List the project's canvases, newest first (capped at 100)."""
        queryset = self._scope_by_project(FileSystem.objects.all()).filter(type="dashboard")
        channel_id = request.query_params.get("channel_id")
        if channel_id:
            channel = self._resolve_channel(channel_id)
            if channel is None:
                return Response({"detail": "Channel not found."}, status=status.HTTP_404_NOT_FOUND)
            queryset = queryset.filter(path__startswith=f"{channel.path}/")
        entries = queryset.order_by("-created_at")[:100]
        return Response(CanvasSummarySerializer([self._canvas_summary(entry) for entry in entries], many=True).data)

    @extend_schema(
        operation_id="desktop_file_system_canvases_create",
        request=CanvasCreateSerializer,
        responses={201: CanvasSummarySerializer},
    )
    @canvases.mapping.post
    def create_canvas(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create a new, empty canvas in a channel.

        The canvas starts with no source; publish a source project to give it one.
        """
        payload = CanvasCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        channel = self._resolve_channel(payload.validated_data["channel_id"])
        if channel is None:
            return Response({"detail": "Channel not found."}, status=status.HTTP_400_BAD_REQUEST)

        # Path segments are "/"-separated, so a name can't contain one (mirrors the app).
        name = re.sub(r"\s+", " ", payload.validated_data["name"].replace("/", " ")).strip() or "Untitled canvas"
        now_ms = int(time.time() * 1000)
        user = request.user if isinstance(request.user, User) else None
        created_by_label = (f"{user.first_name} {user.last_name}".strip() or user.email) if user is not None else None
        meta: dict[str, Any] = {
            "channelId": str(channel.id),
            "templateId": "freeform",
            "createdAt": now_ms,
            "updatedAt": now_ms,
        }
        if created_by_label:
            meta["createdBy"] = created_by_label

        serializer = self.get_serializer(data={"path": f"{channel.path}/{name}", "type": "dashboard", "meta": meta})
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        entry = cast(FileSystem, serializer.instance)
        return Response(CanvasSummarySerializer(self._canvas_summary(entry)).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="desktop_file_system_canvas_source_retrieve",
        responses={200: CanvasSourceResponseSerializer},
    )
    @action(methods=["GET"], detail=True, url_path="canvas/source", request=None)
    def canvas_source(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Read a canvas's source project and the version pointer edits must be based on.

        Legacy single-file canvases are presented as a synthetic web project whose
        `src/canvas.tsx` holds the stored React component.
        """
        dashboard = self._get_dashboard_or_400()
        if isinstance(dashboard, Response):
            return dashboard

        meta = dashboard.meta or {}
        response = {
            "canvas": self._canvas_summary(dashboard),
            "project": synthetic_source_project(meta),
            "current_version_id": meta.get("currentVersionId"),
        }
        return Response(CanvasSourceResponseSerializer(response).data)

    @extend_schema(
        operation_id="desktop_file_system_canvas_validate_create",
        request=CanvasValidateRequestSerializer,
        responses={200: CanvasValidateResponseSerializer},
    )
    @action(methods=["POST"], detail=True, url_path="canvas/validate", request=CanvasValidateRequestSerializer)
    def canvas_validate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Validate a candidate source project without publishing it.

        Side-effect free: returns the same structured diagnostics a publish would
        enforce, so agents can iterate until the project is publishable.
        """
        dashboard = self._get_dashboard_or_400()
        if isinstance(dashboard, Response):
            return dashboard

        payload = CanvasValidateRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        diagnostics = validate_source_project(payload.validated_data["project"])
        response = {"valid": not has_errors(diagnostics), "diagnostics": diagnostics}
        return Response(CanvasValidateResponseSerializer(response).data)

    @extend_schema(
        operation_id="desktop_file_system_canvas_publish_create",
        request=CanvasSourcePublishSerializer,
        responses={
            200: CanvasSourcePublishResponseSerializer,
            400: OpenApiResponse(
                response=CanvasSourceInvalidSerializer,
                description="The source project failed validation; nothing was published.",
            ),
            409: OpenApiResponse(
                response=CanvasPublishConflictSerializer,
                description="The canvas moved past expected_current_version_id (a concurrent publish or an undo).",
            ),
        },
    )
    @action(methods=["POST"], detail=True, url_path="canvas/publish", request=CanvasSourcePublishSerializer)
    def publish_canvas_source(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Publish a complete canvas source project as the canvas's new head version.

        Validates the project first — an error-severity diagnostic rejects the
        publish with 400 and leaves the canvas untouched. Guarded publishing via
        `expected_current_version_id` rejects a stale base with 409 instead of
        overwriting newer work.
        """
        dashboard = self._get_dashboard_or_400()
        if isinstance(dashboard, Response):
            return dashboard

        payload = CanvasSourcePublishSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        return self._publish_source_project(
            request,
            dashboard,
            project=payload.validated_data["project"],
            prompt=payload.validated_data.get("prompt"),
            name=payload.validated_data.get("name"),
            has_expected_version="expected_current_version_id" in payload.validated_data,
            expected_version_id=payload.validated_data.get("expected_current_version_id"),
        )

    def _publish_source_project(
        self,
        request: Request,
        dashboard: FileSystem,
        *,
        project: dict[str, Any],
        prompt: str | None,
        name: str | None,
        has_expected_version: bool,
        expected_version_id: str | None,
    ) -> Response:
        """Validate + publish a complete source project (shared by publish and edit)."""
        diagnostics = validate_source_project(project)
        if has_errors(diagnostics):
            body = {
                "detail": "The source project failed validation; fix the error diagnostics and publish again.",
                "code": "invalid_source_project",
                "diagnostics": diagnostics,
            }
            return Response(CanvasSourceInvalidSerializer(body).data, status=status.HTTP_400_BAD_REQUEST)

        active_builds = CanvasBuild.objects.for_team(self.team_id).filter(
            status__in=[CanvasBuild.STATUS_QUEUED, CanvasBuild.STATUS_BUILDING]
        )
        if active_builds.count() >= MAX_ACTIVE_CANVAS_BUILDS_PER_TEAM:
            return Response(
                {"detail": "Canvas build capacity is temporarily exhausted. Try again shortly."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # Upload-then-commit: the immutable source object goes up before the
        # transaction; a conflicting publish leaves it unreferenced for the
        # retention sweep. Storage being unavailable degrades the publish to
        # legacy-only (no lifecycle rows) instead of failing the canvas save.
        source_object: tuple[str, str, int] | None = None
        try:
            source_object = upload_source_project(self.team_id, dashboard.id, project)
        except ObjectStorageError as error:
            logger.warning("canvas_source_upload_failed", canvas_id=str(dashboard.id), error=str(error))

        record_lifecycle: Callable[[FileSystem, dict[str, Any], dict[str, Any]], None] | None = None
        if source_object is not None:
            uploaded = source_object
            task_id = self._request_task_id(request)
            user = request.user if isinstance(request.user, User) else None

            def _record(locked: FileSystem, meta: dict[str, Any], version: dict[str, Any]) -> None:
                record_publish(
                    locked,
                    meta,
                    project=project,
                    source_object=uploaded,
                    legacy_version_id=version["id"],
                    prompt=prompt,
                    task_id=task_id,
                    created_by_id=user.id if user else None,
                )

            record_lifecycle = _record

        dashboard, conflict, first_publish = self._apply_canvas_publish(
            dashboard,
            code=extract_legacy_code(project),
            prompt=prompt,
            name=name,
            has_expected_version=has_expected_version,
            expected_version_id=expected_version_id,
            record_lifecycle=record_lifecycle,
        )
        if conflict is not None:
            return Response(conflict, status=status.HTTP_409_CONFLICT)

        if first_publish:
            self._announce_canvas_created(request, dashboard)

        meta = dashboard.meta or {}
        response = {
            "canvas": self._canvas_summary(dashboard),
            "current_version_id": meta.get("currentVersionId"),
            "diagnostics": diagnostics,
        }
        return Response(CanvasSourcePublishResponseSerializer(response).data)

    @extend_schema(
        operation_id="desktop_file_system_canvas_edit_create",
        request=CanvasSourceEditSerializer,
        responses={
            200: CanvasSourcePublishResponseSerializer,
            400: OpenApiResponse(
                response=CanvasSourceInvalidSerializer,
                description="An edit targeted a missing file, or the edited project failed validation.",
            ),
            409: OpenApiResponse(
                response=CanvasPublishConflictSerializer,
                description="The canvas moved past expected_current_version_id (a concurrent publish or an undo).",
            ),
        },
    )
    @action(methods=["POST"], detail=True, url_path="canvas/edit", request=CanvasSourceEditSerializer)
    def edit_canvas_source(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Publish per-file edits against the canvas's current source project.

        Diff-aware alternative to sending the complete project: each operation
        sets a file's content or (content null) deletes it, applied to the head
        the caller read. `expected_current_version_id` is mandatory here —
        relative edits against an unverified base could silently merge into
        someone else's newer work, so unguarded diff publishes are refused.
        """
        dashboard = self._get_dashboard_or_400()
        if isinstance(dashboard, Response):
            return dashboard

        payload = CanvasSourceEditSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        project = synthetic_source_project(dashboard.meta or {})
        diagnostics: list[dict[str, Any]] = []
        for operation in payload.validated_data["operations"]:
            path = operation["path"]
            content = operation.get("content")
            if content is None:
                if path not in project["files"]:
                    diagnostics.append(
                        {
                            "severity": "error",
                            "code": "edit_target_missing",
                            "message": f"cannot delete {path} — the project has no file at that path",
                            "path": path,
                        }
                    )
                    continue
                del project["files"][path]
            else:
                project["files"][path] = content
        if diagnostics:
            body = {
                "detail": "The edit could not be applied to the canvas's current source.",
                "code": "invalid_source_project",
                "diagnostics": diagnostics,
            }
            return Response(CanvasSourceInvalidSerializer(body).data, status=status.HTTP_400_BAD_REQUEST)

        return self._publish_source_project(
            request,
            dashboard,
            project=project,
            prompt=payload.validated_data.get("prompt"),
            name=payload.validated_data.get("name"),
            has_expected_version=True,
            expected_version_id=payload.validated_data["expected_current_version_id"],
        )

    @staticmethod
    def _request_task_id(request: Request) -> UUID | None:
        """The publishing task's id, when the sandbox stamped one on the call."""
        raw_task_id = (request.headers.get("X-PostHog-Task-Id") or "").strip()
        try:
            return UUID(raw_task_id)
        except ValueError:
            return None

    @extend_schema(
        operation_id="desktop_file_system_canvas_builds_retrieve",
        responses={200: CanvasBuildsResponseSerializer},
    )
    @action(methods=["GET"], detail=True, url_path="canvas/builds", request=None)
    def canvas_builds(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Read a canvas's build lifecycle: live pointers plus recent builds with diagnostics.

        Poll this after publishing — the publish queues a build, and the
        canvas's `published_build_id` advances only once the build is ready.
        """
        dashboard = self._get_dashboard_or_400()
        if isinstance(dashboard, Response):
            return dashboard

        meta = dashboard.meta or {}
        builds = CanvasBuild.objects.for_team(self.team_id).filter(canvas=dashboard).order_by("-created_at")[:20]
        response = {
            "published_build_id": meta.get("publishedBuildId"),
            "current_source_version_id": meta.get("currentSourceVersionId"),
            "builds": [
                {
                    "id": build.id,
                    "source_version_id": build.source_version_id,
                    "build_status": build.status,
                    "diagnostics": build.diagnostics or [],
                    "manifest": build.manifest,
                    "integrity": build.integrity,
                    "artifact_url": create_canvas_artifact_url(build, build.manifest["entryHtml"])
                    if build.status == CanvasBuild.STATUS_READY and isinstance(build.manifest, dict)
                    else None,
                    "pinned": build.pinned,
                    "created_at": build.created_at,
                    "finished_at": build.finished_at,
                }
                for build in builds
            ],
        }
        return Response(CanvasBuildsResponseSerializer(response).data)

    @extend_schema(
        operation_id="desktop_file_system_canvas_build_action_create",
        request=CanvasBuildActionSerializer,
        responses={200: CanvasBuildSerializer},
    )
    @action(methods=["POST"], detail=True, url_path="canvas/builds/action", request=CanvasBuildActionSerializer)
    def canvas_build_action(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        dashboard = self._get_dashboard_or_400()
        if isinstance(dashboard, Response):
            return dashboard
        serializer = CanvasBuildActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action_name = serializer.validated_data["action"]
        with transaction.atomic():
            build = (
                CanvasBuild.objects.for_team(self.team_id)
                .select_for_update()
                .filter(id=serializer.validated_data["build_id"], canvas=dashboard)
                .first()
            )
            if build is None:
                return Response({"detail": "Canvas build not found."}, status=status.HTTP_404_NOT_FOUND)
            if action_name == "retry":
                if build.status != CanvasBuild.STATUS_FAILED:
                    return Response({"detail": "Only failed builds can be retried."}, status=status.HTTP_409_CONFLICT)
                build = CanvasBuild.objects.create(
                    team_id=self.team_id,
                    canvas=dashboard,
                    source_version=build.source_version,
                    status=CanvasBuild.STATUS_QUEUED,
                )
                from posthog.tasks.canvas_build import process_canvas_build  # noqa: PLC0415

                transaction.on_commit(lambda: process_canvas_build.delay(self.team_id, str(build.id)))
            elif action_name == "cancel":
                if build.status != CanvasBuild.STATUS_QUEUED:
                    return Response({"detail": "Only queued builds can be cancelled."}, status=status.HTTP_409_CONFLICT)
                build.status = CanvasBuild.STATUS_FAILED
                build.diagnostics = [
                    {"severity": "warning", "code": "cancelled", "message": "The canvas build was cancelled."}
                ]
                build.finished_at = timezone.now()
                build.save(update_fields=["status", "diagnostics", "finished_at"])
            else:
                build.pinned = action_name == "pin"
                build.save(update_fields=["pinned"])
        return Response(
            CanvasBuildSerializer(
                {
                    "id": build.id,
                    "source_version_id": build.source_version_id,
                    "build_status": build.status,
                    "diagnostics": build.diagnostics,
                    "manifest": build.manifest,
                    "integrity": build.integrity,
                    "artifact_url": create_canvas_artifact_url(build, build.manifest["entryHtml"])
                    if build.status == CanvasBuild.STATUS_READY and isinstance(build.manifest, dict)
                    else None,
                    "pinned": build.pinned,
                    "created_at": build.created_at,
                    "finished_at": build.finished_at,
                }
            ).data
        )

    def _announce_canvas_created(self, request: Request, dashboard: FileSystem) -> None:
        """Announce a canvas's first publish in the generating task's thread.

        The task sandbox stamps every MCP call with an X-PostHog-Task-Id header, so
        a publish is attributable to the task that made it. The header alone is
        forgeable, so two checks bind the announcement to a real sandbox run: the
        request must carry an OAuth token minted under a sandbox app (those tokens
        are only created server-side), and the facade only accepts a task created
        by the requesting user (the sandbox authenticates with the task creator's
        credentials). No header (a human or app save) means no announcement.
        """
        raw_task_id = (request.headers.get("X-PostHog-Task-Id") or "").strip()
        try:
            task_id = UUID(raw_task_id)
        except ValueError:
            return
        if not self._is_sandbox_authenticated(request):
            return
        user = request.user if isinstance(request.user, User) else None
        segments = split_path(dashboard.path)
        tasks_facade.post_canvas_created_thread_update(
            task_id,
            self.team_id,
            acting_user_id=user.id if user else None,
            canvas_name=segments[-1] if segments else "Canvas",
            canvas_url=self._canvas_share_url(dashboard),
        )

    @staticmethod
    def _is_sandbox_authenticated(request: Request) -> bool:
        """True when the request bears an OAuth token minted under a sandbox app —
        the credential a task sandbox (via the MCP server) calls this API with."""
        authenticator = request.successful_authenticator
        if not isinstance(authenticator, OAuthAccessTokenAuthentication):
            return False
        application = authenticator.access_token.application
        return application is not None and application.client_id in SANDBOX_OAUTH_APP_CLIENT_IDS

    def _canvas_share_url(self, dashboard: FileSystem) -> str | None:
        """The web interstitial link that deep-links into the desktop app's canvas view:
        `/code/canvas/<channel folder id>/<dashboard id>`. The channel id is stamped on
        the row's meta by the desktop app at create time; fall back to the parent folder
        row for rows that predate the stamp.
        """
        channel_id = (dashboard.meta or {}).get("channelId")
        if not channel_id:
            parent_path = join_path(split_path(dashboard.path)[:-1])
            folder = (
                FileSystem.objects.filter(
                    surface_q(self.file_system_surface),
                    team_id=dashboard.team_id,
                    type="folder",
                    path=parent_path,
                ).first()
                if parent_path
                else None
            )
            channel_id = str(folder.id) if folder else None
        if not channel_id:
            return None
        return f"{settings.SITE_URL}/code/canvas/{channel_id}/{dashboard.id}"

    @extend_schema(responses={200: FolderInstructionsSerializer})
    @action(methods=["GET"], detail=True)
    def instructions(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Return the latest non-deleted instructions for this folder."""
        folder = self._get_folder_or_400()
        if isinstance(folder, Response):
            return folder

        latest = get_latest_folder_instructions(folder)
        if latest is None:
            return Response({"detail": "This folder has no instructions."}, status=status.HTTP_404_NOT_FOUND)

        return Response(FolderInstructionsSerializer(latest).data)

    @extend_schema(request=FolderInstructionsPublishSerializer, responses={200: FolderInstructionsSerializer})
    @instructions.mapping.put
    @instructions.mapping.patch
    def publish_instructions(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Publish a new version of the folder's instructions."""
        folder = self._get_folder_or_400()
        if isinstance(folder, Response):
            return folder

        payload = FolderInstructionsPublishSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        try:
            published = publish_folder_instructions(
                folder,
                content=payload.validated_data["content"],
                user=cast(User, request.user),
                base_version=payload.validated_data.get("base_version"),
            )
        except FolderInstructionsVersionConflictError as err:
            return Response(
                {
                    "detail": "The instructions changed since you opened them. Reload the latest version and try again.",
                    "current_version": err.current_version,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except FolderInstructionsVersionLimitError as err:
            return Response(
                {"detail": f"This folder has reached the maximum of {err.max_version} instruction versions."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(FolderInstructionsSerializer(published).data)

    @extend_schema(request=None, responses={204: None})
    @instructions.mapping.delete
    def delete_instructions(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Soft-delete every version of this folder's instructions."""
        folder = self._get_folder_or_400()
        if isinstance(folder, Response):
            return folder

        deleted_count = delete_folder_instructions(folder)
        if deleted_count == 0:
            return Response({"detail": "This folder has no instructions."}, status=status.HTTP_404_NOT_FOUND)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={200: FolderInstructionsVersionSerializer(many=True)})
    @action(methods=["GET"], detail=True, url_path="instructions/versions")
    def instructions_versions(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """List the version history for this folder's instructions, newest first."""
        folder = self._get_folder_or_400()
        if isinstance(folder, Response):
            return folder

        versions = get_folder_instructions_versions(folder)
        page = self.paginate_queryset(versions)
        if page is not None:
            return self.get_paginated_response(FolderInstructionsVersionSerializer(page, many=True).data)
        return Response(FolderInstructionsVersionSerializer(versions, many=True).data)

    @extend_schema(responses={200: ContextGenerationSerializer})
    @action(methods=["GET"], detail=True, url_path="context_generation")
    def context_generation(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Return the Task currently generating this folder's CONTEXT.md, or null if none."""
        folder = self._get_folder_or_400()
        if isinstance(folder, Response):
            return folder

        return Response(ContextGenerationSerializer({"task_id": get_context_generation_task_id(folder)}).data)

    @extend_schema(request=ContextGenerationSetSerializer, responses={200: ContextGenerationSerializer})
    @context_generation.mapping.put
    def set_context_generation(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Set or clear the Task associated with this folder's CONTEXT.md generation."""
        folder = self._get_folder_or_400()
        if isinstance(folder, Response):
            return folder

        payload = ContextGenerationSetSerializer(data=request.data, context={"folder_team": folder.team})
        payload.is_valid(raise_exception=True)
        task_id = payload.validated_data["task_id"]
        set_context_generation_task_id(folder, task_id=task_id)

        return Response(ContextGenerationSerializer({"task_id": task_id}).data)
