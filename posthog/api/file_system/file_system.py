import re
import json
import shlex
import logging
import builtins
from functools import cached_property
from typing import Any, Optional, cast
from uuid import UUID

from django.db import transaction
from django.db.models import Case, F, IntegerField, Q, QuerySet, Value, When
from django.db.models.functions import Concat, Lower

from drf_spectacular.utils import extend_schema
from rest_framework import filters, pagination, serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.file_system.access_levels import (
    FileSystemAccessLevelSerializerMixin,
    denied_short_id_refs,
    entries_missing_access_level,
)
from posthog.api.file_system.deletion import (
    HOG_FUNCTION_TYPES,
    delete_file_system_object,
    get_restorable_object,
    is_file_system_type_registered,
    undo_delete as undo_delete_object,
)
from posthog.api.file_system.file_system_logging import log_api_file_system_view
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
from posthog.settings import EE_AVAILABLE
from posthog.utils import str_to_bool

logger = logging.getLogger(__name__)

DELETE_PREVIEW_ENTRY_LIMIT = 200

# One message for every reason a restore is refused (missing, already live, or off-limits), so the
# endpoint can't be used to learn which refs exist.
UNDO_DELETE_REFUSED = "Couldn't restore this. It may already be restored, or you may not have access to it."

# Paths the product itself builds are at most three segments deep ("Unfiled/Insights/<name>"), so
# these leave ample headroom for hand-made trees while keeping the per-segment folder creation in
# `_assure_parent_folders` (one existence check plus one insert each) bounded.
MAX_PATH_LENGTH = 4000
MAX_PATH_SEGMENTS = 50

# `meta` is a free-form client blob, so it only needs a ceiling that keeps a single row from
# dominating a page of list results.
MAX_META_BYTES = 1_000_000

# Search-within-Recents scans this many of the user's most-recent views, then the text filter trims
# them to a page. Bounds the hydration key set so the query stays cheap on heavy view-log histories.
RECENTS_SEARCH_SCAN_LIMIT = 200


def validate_file_system_path(path: Any) -> str:
    """Bound a caller-supplied path before it reaches the per-segment folder creation loop, which
    costs one existence check plus one insert per segment and autocommits each one."""
    if not isinstance(path, str):
        raise serializers.ValidationError("Path must be a string.")
    if len(path) > MAX_PATH_LENGTH:
        raise serializers.ValidationError(f"Path must be {MAX_PATH_LENGTH} characters or fewer.")
    if len(split_path(path)) > MAX_PATH_SEGMENTS:
        raise serializers.ValidationError(f"Path can be at most {MAX_PATH_SEGMENTS} levels deep.")
    return path


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

    def validate_path(self, path: str) -> str:
        return validate_file_system_path(path)

    def validate_meta(self, meta: Any) -> dict[str, Any]:
        # Readers treat `meta` as an object, so anything else stored here breaks every listing that
        # includes the row, not just the writer's own request.
        if not isinstance(meta, dict):
            raise serializers.ValidationError("Meta must be an object.")
        if len(json.dumps(meta, default=str).encode()) > MAX_META_BYTES:
            raise serializers.ValidationError(f"Meta must be smaller than {MAX_META_BYTES / 1_000_000:g} MB.")
        return meta

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

    def validate_path(self, value: str) -> str:
        # Restoring re-creates parent folders through the same per-segment loop as create/move/link.
        return validate_file_system_path(value)


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
    # on its own route. The default surface also matches legacy NULL rows.
    file_system_surface: str = DEFAULT_SURFACE
    # GET /instructions/ and /instructions/versions/ are reads; PUT/PATCH/DELETE on
    # /instructions/ resolve to `publish_instructions` / `delete_instructions` via DRF's
    # method mapping, so they go in the write bucket.
    scope_object_read_actions = [
        "list",
        "retrieve",
        "unfiled",
        "count",
        "count_by_path",
    ]
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "move",
        "link",
        "log_view",
        "undo_delete",
    ]

    @cached_property
    def _denied_short_id_refs(self) -> dict[tuple[str, int], builtins.list[str]]:
        if not self.user_access_control:
            return {}
        return denied_short_id_refs(self.user_access_control, self.team.project_id)

    @cached_property
    def _accessible_team_ids(self) -> Optional[set[int]]:
        """Environments in this project the user may see, or None when nothing needs filtering.

        The tree deliberately spans every environment in the project, but project-level access is
        configured per environment and a user can be denied one outright. Resource and object
        rules don't express that: an environment with no rules of its own falls back to the
        resource default, so a denied environment's rows would otherwise list and resolve as
        editable. Mirrors the carve-outs in `filter_and_annotate_file_system_queryset`, which
        already lets staff and org admins past every other check here.
        """
        user_access_control = self.user_access_control
        if not user_access_control:
            return None
        if self.request.user.is_staff or user_access_control.is_organization_admin:
            return None
        if not EE_AVAILABLE or not user_access_control.access_controls_supported:
            return None

        team_ids = Team.objects.filter(project_id=self.team.project_id).values_list("id", flat=True)
        return {
            team_id
            for team_id, team_access in user_access_control.for_team_ids(team_ids).items()
            if team_access.has_project_access
        }

    def _filter_by_access_control(self, queryset: QuerySet) -> QuerySet:
        if not self.user_access_control:
            return queryset
        accessible_team_ids = self._accessible_team_ids
        if accessible_team_ids is not None:
            queryset = queryset.filter(team_id__in=accessible_team_ids)
        return self.user_access_control.filter_and_annotate_file_system_queryset(
            queryset, extra_denied_refs=self._denied_short_id_refs
        )

    def _ensure_can_delete_objects(self, objects: builtins.list[tuple[str, str, int]]) -> None:
        """Require editor access on every backing object the delete would reach.

        The tree row itself has no access controls, so without this a delete routed through the
        file system would bypass the level the object's own resource model requires. `objects` is
        (type, ref, team_id) - team_id is each row's own team, since the tree can list rows from
        sibling environments and the check has to run against the object's real team.
        """
        if not objects or not self.user_access_control:
            return
        denied = entries_missing_access_level(objects, self.user_access_control, self.team.project_id, "editor")
        if denied:
            raise PermissionDenied("You need editor access to delete this. Ask a project admin to grant it.")

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

        queryset = self._filter_by_access_control(queryset)

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
        # without a second round-trip. Rows written before `meta` was validated can hold a
        # non-object value, and one of those must not take down the whole listing.
        user_ids = set()
        for item in results:
            meta = item.get("meta")
            if not isinstance(meta, dict):
                continue
            created_by = meta.get("created_by")
            if isinstance(created_by, int) and created_by:
                user_ids.add(created_by)
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
        base_queryset = self._filter_by_access_control(base_queryset)
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

    def _ensure_can_delete(self, entry: FileSystem) -> dict[UUID, bool]:
        """Decide, and authorize, which of `entry`'s leaf rows carry the delete through to their
        backing object - and lock that decision so a concurrent request can't change it before
        `_delete_file_system_entry` acts on it (see the locking note below).

        Returns a `{row_id: reaches_backing_object}` map that `destroy()` passes straight into
        `_delete_file_system_entry`, so the actual delete reuses this locked decision instead of
        recomputing an unlocked count of its own - two independent unlocked counts would let a
        second concurrent delete of a sibling row change the answer in between, deleting the
        backing object without ever having been through the editor check above.
        """
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
                descendants = self._filter_by_access_control(descendants)
                stack.extend(descendants)
                continue

            entries_to_check.append(current)

        if not entries_to_check:
            return {}

        ids_to_remove = {entry.id for entry in entries_to_check}

        # Several leaf rows can share one (team, type, ref) - that's the "last reference" case
        # this whole check exists for - and a folder cascade can span several distinct objects.
        # Group first so each distinct object is locked and counted exactly once, however many
        # rows in this batch reference it.
        # A ref-less row references no object, so it has no siblings to share a count with. It is
        # keyed by its own id rather than pooled with every other ref-less row of its type, which
        # would treat unrelated rows as references to one object.
        entries_by_group: dict[tuple[int, str, Optional[str], str], list[FileSystem]] = {}
        for current in entries_to_check:
            group_key = (current.team_id, current.type, current.ref, "" if current.ref else str(current.id))
            entries_by_group.setdefault(group_key, []).append(current)

        objects_to_delete: builtins.list[tuple[str, str, int]] = []
        reaches_backing_object: dict[UUID, bool] = {}

        # Sorted so concurrent requests whose cascades overlap on more than one object always
        # acquire the per-object locks in the same order - locking in traversal order (DFS over
        # an unordered queryset) could have two such requests lock the same two objects in
        # opposite order and deadlock, same failure mode `.order_by("id")` below prevents within
        # one object's sibling set.
        for (team_id, file_type, ref, _row_key), group in sorted(
            entries_by_group.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or "", kv[0][3])
        ):
            if ref is None:
                # No ref means no shared backing object, so there is no sibling set to count and
                # nothing for a concurrent delete to race us to. Locking on (team, type, NULL)
                # would instead row-lock every ref-less row of this type in the team for the rest
                # of the transaction, serializing unrelated deletes behind this one.
                remaining = 0
            else:
                # Lock every row referencing this object (not just the ones outside ids_to_remove)
                # so a concurrent request deleting a sibling row locks the same row set in the
                # same order and blocks on it, rather than each request locking a different subset
                # and deadlocking against the other.
                sibling_ids = {
                    row.id
                    for row in FileSystem.objects.select_for_update()
                    .filter(team_id=team_id, type=file_type, ref=ref, shortcut=False)
                    .order_by("id")
                }
                remaining = len(sibling_ids - ids_to_remove)
            # When several rows in this batch reference the same object, only one of them may
            # actually carry the deletion through - otherwise every row in the group would call
            # delete_file_system_object independently, running its hooks and activity logging
            # once per row instead of once for the object.
            for current in group:
                reaches_backing_object[current.id] = False
            reaches_backing_object[group[0].id] = remaining == 0

            if not is_file_system_type_registered(file_type):
                continue

            if remaining == 0 and not ref:
                # A registered-type row with no ref is a data-integrity error we refuse to delete.
                raise serializers.ValidationError({"detail": f"Cannot delete type '{file_type}' without a reference."})

            # Only the last row referencing an object carries the deletion through to the object
            # itself; removing one of several rows leaves it untouched.
            if remaining == 0 and ref:
                objects_to_delete.append((file_type, ref, team_id))

        self._ensure_can_delete_objects(objects_to_delete)

        return reaches_backing_object

    def _delete_file_system_entry(
        self, entry: FileSystem, reaches_backing_object: dict[UUID, bool]
    ) -> builtins.list[dict[str, Any]]:
        deleted_objects: list[dict[str, Any]] = []

        if entry.shortcut:
            entry.delete()
            return deleted_objects

        if entry.type == "folder":
            descendants = FileSystem.objects.filter(path__startswith=f"{entry.path}/")
            descendants = self._scope_by_project_and_environment(descendants)
            descendants = self._filter_by_access_control(descendants)
            for child in descendants.order_by("depth", "path"):
                deleted_objects.extend(self._delete_file_system_entry(child, reaches_backing_object))
            entry.delete()
            return deleted_objects

        if not is_file_system_type_registered(entry.type):
            raise serializers.ValidationError({"detail": f"Cannot delete resources with type '{entry.type}'."})

        # Reuses the locked decision from _ensure_can_delete rather than recounting - a row this
        # method discovers on its own (e.g. created after that pass ran) defaults to "leave the
        # backing object alone", the same safe outcome an unauthorized delete would get.
        if not reaches_backing_object.get(entry.id, False):
            entry.delete()
            return deleted_objects

        if not entry.ref:
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
            reaches_backing_object = self._ensure_can_delete(instance)
            deleted_objects = self._delete_file_system_entry(instance, reaches_backing_object)

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

        # Each restore locks its target row and holds it to the end of the transaction, so two
        # requests naming the same objects in opposite order would each hold one and block on the
        # other. Sorting means every request takes those locks in the same order instead.
        items = sorted(serializer.validated_data["items"], key=lambda item: (item["type"], item["ref"]))
        undo_results: list[dict[str, str]] = []

        with transaction.atomic():
            for item in items:
                self._ensure_can_restore(item["type"], item["ref"])
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
                    logger.exception(
                        "Exception during undo_delete_object (type=%s, ref=%s)", item.get("type"), item.get("ref")
                    )
                    raise serializers.ValidationError({"detail": UNDO_DELETE_REFUSED})
                self._restore_file_system_path(restored_instance, item)
                undo_results.append({"type": item["type"], "ref": item["ref"]})

        return Response({"undone": undo_results}, status=status.HTTP_200_OK)

    def _ensure_can_restore(self, type_string: str, ref: str) -> None:
        """`undo_delete` takes a caller-supplied (type, ref) rather than a tree row, so neither
        the tree's visibility filter nor `get_object` has run by the time we get here."""
        instance = get_restorable_object(type_string, ref, team_id=self.team.id)
        allowed = instance is not None and (
            not self.user_access_control
            or self.user_access_control.check_access_level_for_object(instance, required_level="editor")
        )
        if not allowed:
            raise serializers.ValidationError({"detail": UNDO_DELETE_REFUSED})

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
            qs = self._filter_by_access_control(qs)
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
        new_path = validate_file_system_path(new_path)

        self._assure_parent_folders(new_path, cast(User, request.user))

        if instance.type == "folder":
            if new_path == instance.path:
                return Response({"detail": "Cannot move folder into itself"}, status=status.HTTP_400_BAD_REQUEST)

            with transaction.atomic():
                qs = FileSystem.objects.filter(path__startswith=f"{instance.path}/")
                qs = self._scope_by_project_and_environment(qs)
                qs = self._filter_by_access_control(qs)
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
        new_path = validate_file_system_path(new_path)

        self._assure_parent_folders(new_path, cast(User, request.user))

        if instance.type == "folder":
            if new_path == instance.path:
                return Response({"detail": "Cannot link folder into itself"}, status=status.HTTP_400_BAD_REQUEST)

            with transaction.atomic():
                qs = FileSystem.objects.filter(path__startswith=f"{instance.path}/")
                qs = self._scope_by_project_and_environment(qs)
                qs = self._filter_by_access_control(qs)

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
        qs = self._filter_by_access_control(qs)

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
        qs = self._filter_by_access_control(qs)

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
