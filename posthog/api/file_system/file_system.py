import re
import time
import shlex
import builtins
from typing import Any, cast
from uuid import uuid4

from django.db import transaction
from django.db.models import Case, F, IntegerField, Q, QuerySet, Value, When
from django.db.models.functions import Concat, Lower

from drf_spectacular.utils import extend_schema
from rest_framework import filters, pagination, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.file_system.access_levels import FileSystemAccessLevelSerializerMixin
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
from posthog.decorators import disallow_if_impersonated
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
from posthog.utils import str_to_bool

DELETE_PREVIEW_ENTRY_LIMIT = 200

# Search-within-Recents scans this many of the user's most-recent views, then the text filter trims
# them to a page. Bounds the hydration key set so the query stays cheap on heavy view-log histories.
RECENTS_SEARCH_SCAN_LIMIT = 200


class FileSystemSerializer(FileSystemAccessLevelSerializerMixin, serializers.ModelSerializer):
    last_viewed_at = serializers.DateTimeField(read_only=True, allow_null=True)

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


class CanvasPublishSerializer(serializers.Serializer):
    """Payload for publishing a freeform canvas's React source via the agent."""

    code = serializers.CharField(allow_blank=True, trim_whitespace=False)
    prompt = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    name = serializers.CharField(required=False, allow_blank=False, trim_whitespace=True)


@extend_schema(extensions={"x-product": "core"})
class DesktopFileSystemViewSet(FileSystemViewSet):
    """
    The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
    scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.

    Adds per-folder, versioned markdown instructions describing the contents of a folder.
    """

    file_system_surface = "desktop"

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

    @extend_schema(
        operation_id="desktop_file_system_canvas_partial_update",
        request=CanvasPublishSerializer,
        responses={200: FileSystemSerializer},
    )
    @action(methods=["PATCH"], detail=True, url_path="canvas")
    def publish_canvas(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Publish a new version of a freeform canvas's React source.

        Merges into the dashboard row's `meta` (never replaces it), so existing
        keys like `channelId`/`templateId` survive. Appends a full-file version
        snapshot and points `currentVersionId` at it — the server-side mirror of
        the app's dashboardsService.saveFreeform.
        """
        dashboard = self._get_dashboard_or_400()
        if isinstance(dashboard, Response):
            return dashboard

        payload = CanvasPublishSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        code = payload.validated_data["code"]
        prompt = payload.validated_data.get("prompt")
        name = payload.validated_data.get("name")

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
            # Snapshot the live author context onto the version (reverting restores it).
            existing_context = meta.get("context")
            if isinstance(existing_context, str):
                version["context"] = existing_context
            versions = list(meta.get("versions") or [])
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

        return Response(self.get_serializer(dashboard).data)

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
