import re
import shlex
from typing import Any, Optional, cast

from django.db import transaction
from django.db.models import Case, F, IntegerField, Q, QuerySet, Value, When
from django.db.models.functions import Concat, Lower

from rest_framework import filters, pagination, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.file_system.file_system_logging import log_api_file_system_view
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.models.activity_logging.model_activity import is_impersonated_session
from posthog.models.file_system.file_system import FileSystem, join_path, split_path
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.file_system.file_system_view_log import FileSystemViewLog, annotate_file_system_with_view_logs
from posthog.models.file_system.unfiled_file_saver import save_unfiled_files
from posthog.models.team import Team
from posthog.models.user import User

HOG_FUNCTION_TYPES = ["broadcast", "campaign", "destination", "site_app", "source", "transformation"]


class FileSystemSerializer(serializers.ModelSerializer):
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
        ]
        read_only_fields = [
            "id",
            "depth",
            "created_at",
            "team_id",
            "last_viewed_at",
        ]

    def update(self, instance: FileSystem, validated_data: dict[str, Any]) -> FileSystem:
        if "path" in validated_data:
            instance.depth = len(split_path(validated_data["path"]))
        return super().update(instance, validated_data)

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> FileSystem:
        request = self.context["request"]
        team = self.context["get_team"]()

        full_path = validated_data["path"]
        segments = split_path(full_path)

        for depth_index in range(1, len(segments)):
            parent_path = "/".join(segments[:depth_index])
            folder_exists = FileSystem.objects.filter(team=team, path=parent_path).exists()
            if not folder_exists:
                FileSystem.objects.create(
                    team=team,
                    path=parent_path,
                    depth=depth_index,
                    type="folder",
                    created_by=request.user,
                    shortcut=False,
                )

        if validated_data.get("shortcut") is None:
            validated_data["shortcut"] = False

        depth = len(segments)
        file_system = FileSystem.objects.create(
            team=team,
            created_by=request.user,
            depth=depth,
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


class FileSystemViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "file_system"
    queryset = FileSystem.objects.select_related("created_by")
    serializer_class = FileSystemSerializer
    filter_backends = [filters.SearchFilter]
    pagination_class = FileSystemsLimitOffsetPagination

    def _apply_search_to_queryset(self, queryset: QuerySet, search: str) -> QuerySet:
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
                    regex = rf"(^|(?<!\\)/)([^/]|\\.)*{re.escape(value)}([^/]|\\.)*$"
                    q = Q(path__iregex=regex)

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
            elif "/" in token:
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
                # plain free-text token: search in path or type
                q = Q(path__icontains=token) | Q(type__icontains=token)

            combined_q &= ~q if negated else q

        return queryset.filter(combined_q)

    def _scope_by_project(self, queryset: QuerySet) -> QuerySet:
        """
        Show all objects belonging to the project.
        """
        return queryset.filter(team__project_id=self.team.project_id)

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
            queryset = self._apply_search_to_queryset(queryset, search_param)

        if self.user_access_control:
            queryset = self.user_access_control.filter_and_annotate_file_system_queryset(queryset)

        if ref_param:
            queryset = queryset.filter(ref=ref_param)
            queryset = queryset.order_by("shortcut")  # override order
        elif order_by_param:
            if order_by_param in ["path", "-path", "created_at", "-created_at"]:
                queryset = queryset.order_by(order_by_param)
            elif order_by_param == "-last_viewed_at" and self.request.user.is_authenticated:
                queryset = annotate_file_system_with_view_logs(
                    team_id=self.team.id,
                    user_id=self.request.user.id,
                    queryset=queryset,
                )
                queryset = queryset.order_by(F("last_viewed_at").desc(nulls_last=True), "-created_at")
            elif order_by_param == "last_viewed_at" and self.request.user.is_authenticated:
                queryset = annotate_file_system_with_view_logs(
                    team_id=self.team.id,
                    user_id=self.request.user.id,
                    queryset=queryset,
                )
                queryset = queryset.order_by(F("last_viewed_at").asc(nulls_first=True), "created_at")
            else:
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
        response = super().list(request, *args, **kwargs)
        results = response.data.get("results", [])
        user_ids = set()

        # Collect user IDs from the "created_by" meta field
        for item in results:
            created_by = item.get("meta", {}).get("created_by")
            if created_by and isinstance(created_by, int):
                user_ids.add(created_by)

        if user_ids:
            users_qs = User.objects.filter(organization=self.organization, id__in=user_ids).distinct()
            response.data["users"] = UserBasicSerializer(users_qs, many=True).data
        else:
            response.data["users"] = []

        return response

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.type == "folder":
            path = instance.path
            qs = FileSystem.objects.filter(path__startswith=f"{path}/")
            qs = self._scope_by_project_and_environment(qs)
            if self.user_access_control:
                qs = self.user_access_control.filter_and_annotate_file_system_queryset(qs)
            with transaction.atomic():
                qs.delete()
                instance.delete()
            # Repair folder tree for items we *didn't* move (hog functions in other teams under the moved folder)
            leftovers = self._scope_by_project(FileSystem.objects.filter(path__startswith=f"{path}/"))
            first_leftover = leftovers.first()
            if first_leftover:
                self._assure_parent_folders(first_leftover.path, instance.created_by, first_leftover.team)
        else:
            instance.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["GET"], detail=False)
    def unfiled(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query_serializer = UnfiledFilesQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        file_type = query_serializer.validated_data.get("type")
        files = save_unfiled_files(self.team, cast(User, request.user), file_type)

        self._retroactively_fix_folders_and_depth(cast(User, request.user))

        if self.user_access_control:
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

        qs = FileSystem.objects.filter(path__startswith=f"{instance.path}/")
        qs = self._scope_by_project_and_environment(qs)
        if self.user_access_control:
            qs = self.user_access_control.filter_and_annotate_file_system_queryset(qs)

        return Response({"count": qs.count()}, status=status.HTTP_200_OK)

    @action(methods=["GET", "POST"], detail=False, url_path="log_view")
    def log_view(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if request.method == "GET":
            return self._list_log_views(request)

        if is_impersonated_session(request):
            return Response(
                {"detail": "Impersonated sessions cannot log file system views."},
                status=status.HTTP_403_FORBIDDEN,
            )

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

        queryset = FileSystemViewLog.objects.filter(team=self.team, user=request.user)
        log_type = validated.get("type")
        if log_type:
            queryset = queryset.filter(type=log_type)

        queryset = queryset.order_by("-viewed_at")

        limit = validated.get("limit")
        if limit is not None:
            queryset = queryset[:limit]

        return Response(FileSystemViewLogSerializer(queryset, many=True).data)

    @action(methods=["POST"], detail=False)
    def count_by_path(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Get count of all files in a folder."""
        path_param = self.request.query_params.get("path")
        if not path_param:
            return Response({"detail": "path parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        qs = FileSystem.objects.filter(path__startswith=f"{path_param}/")
        qs = self._scope_by_project_and_environment(qs)
        if self.user_access_control:
            qs = self.user_access_control.filter_and_annotate_file_system_queryset(qs)

        return Response({"count": qs.count()}, status=status.HTTP_200_OK)

    def _assure_parent_folders(self, path: str, created_by: User, team: Optional[Team] = None) -> None:
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
                        )
                    )

        if folders_to_create:
            FileSystem.objects.bulk_create(folders_to_create)

        if items_to_update:
            for item in items_to_update:
                item.save()
