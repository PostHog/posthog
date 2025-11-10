import re
import shlex
import builtins
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Optional, cast

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
from posthog.models.action.action import Action
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.activity_logging.model_activity import is_impersonated_session
from posthog.models.cohort import Cohort
from posthog.models.dashboard import Dashboard
from posthog.models.experiment import Experiment
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.file_system.file_system import FileSystem, create_or_update_file, join_path, split_path
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.file_system.file_system_view_log import FileSystemViewLog, annotate_file_system_with_view_logs
from posthog.models.file_system.unfiled_file_saver import save_unfiled_files
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.insight import Insight
from posthog.models.link import Link
from posthog.models.surveys.survey import Survey
from posthog.models.team import Team
from posthog.models.user import User
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.session_recording_playlist_api import log_playlist_activity

from products.early_access_features.backend.models import EarlyAccessFeature
from products.notebooks.backend.api.notebook import log_notebook_activity
from products.notebooks.backend.models import Notebook

HOG_FUNCTION_TYPES = ["broadcast", "campaign", "destination", "site_app", "source", "transformation"]


# Used to gather delete operations
@dataclass(frozen=True)
class DeleteHandler:
    delete: Callable[["FileSystemViewSet", FileSystem], None]
    mode: Literal["soft", "hard"]
    undo: str
    restore: Optional[Callable[["FileSystemViewSet", dict[str, Any]], Any]] = None


def _log_file_system_activity(
    viewset: "FileSystemViewSet",
    *,
    scope: str,
    activity: Literal["deleted", "updated"],
    item_id: str | int,
    name: Optional[str] = None,
    short_id: Optional[str] = None,
    changes: Optional[list[Change]] = None,
) -> None:
    organization = getattr(viewset, "organization", None)
    if not organization:
        return

    log_activity(
        organization_id=organization.id,
        team_id=viewset.team_id,
        user=cast(User, viewset.request.user),
        was_impersonated=is_impersonated_session(viewset.request),
        item_id=str(item_id),
        scope=scope,
        activity=activity,
        detail=Detail(name=name, short_id=short_id, changes=changes),
    )


def _log_restore_activity(
    viewset: "FileSystemViewSet",
    *,
    scope: str,
    item_id: str | int,
    name: Optional[str] = None,
    short_id: Optional[str] = None,
    extra_changes: Optional[list[Change]] = None,
) -> None:
    changes = extra_changes or []
    changes.append(Change(type=scope, action="changed", field="deleted", before=True, after=False))
    _log_file_system_activity(
        viewset,
        scope=scope,
        activity="updated",
        item_id=item_id,
        name=name,
        short_id=short_id,
        changes=changes,
    )


# Set deleted=True on instance
def _soft_delete(instance: Any, *, field: str = "deleted", extra_updates: Optional[dict[str, Any]] = None) -> None:
    update_fields: list[str] = []
    if extra_updates:
        for attr, value in extra_updates.items():
            if getattr(instance, attr) != value:
                setattr(instance, attr, value)
                update_fields.append(attr)
    if getattr(instance, field) is not True:
        setattr(instance, field, True)
        update_fields.append(field)
    if update_fields:
        instance.save(update_fields=update_fields)
    else:
        # Ensure post_save triggers even if nothing changed
        instance.save()


# Set deleted=False on instance and restore the file system row
def _restore_soft_delete(
    instance: Any,
    *,
    field: str = "deleted",
    extra_updates: Optional[dict[str, Any]] = None,
    restore_path: Optional[str] = None,
) -> Any:
    if restore_path is not None and hasattr(instance, "_create_in_folder"):
        segments = split_path(restore_path)
        folder_path = join_path(segments[:-1]) if len(segments) > 1 else ""
        instance._create_in_folder = folder_path or None
    update_fields: list[str] = []
    if getattr(instance, field) is not False:
        setattr(instance, field, False)
        update_fields.append(field)
    if extra_updates:
        for attr, value in extra_updates.items():
            if getattr(instance, attr) != value:
                setattr(instance, attr, value)
                update_fields.append(attr)
    if update_fields:
        instance.save(update_fields=update_fields)
    else:
        instance.save()
    return instance


def _require_entry_ref(entry: FileSystem) -> str:
    ref = entry.ref
    if ref is None:
        raise serializers.ValidationError({"detail": f"Cannot delete type '{entry.type}' without a reference."})
    return ref


def _delete_action(viewset: "FileSystemViewSet", entry: FileSystem) -> None:
    action = Action.objects.get(team=entry.team, id=_require_entry_ref(entry))
    _soft_delete(action)


def _restore_action(viewset: "FileSystemViewSet", payload: dict[str, Any]) -> Action:
    action = Action.objects.get(team=viewset.team, id=payload["ref"])
    return cast(Action, _restore_soft_delete(action, restore_path=payload.get("path")))


def _delete_dashboard(viewset: "FileSystemViewSet", entry: FileSystem) -> None:
    dashboard = Dashboard.objects_including_soft_deleted.get(team=entry.team, id=_require_entry_ref(entry))
    if dashboard.deleted:
        dashboard.save(update_fields=["deleted"])
    else:
        dashboard.deleted = True
        dashboard.save(update_fields=["deleted"])


def _restore_dashboard(viewset: "FileSystemViewSet", payload: dict[str, Any]) -> Dashboard:
    dashboard = Dashboard.objects_including_soft_deleted.get(team=viewset.team, id=payload["ref"])
    return cast(Dashboard, _restore_soft_delete(dashboard, restore_path=payload.get("path")))


def _delete_feature_flag(viewset: "FileSystemViewSet", entry: FileSystem) -> None:
    flag = FeatureFlag.objects.get(team=entry.team, id=_require_entry_ref(entry))
    _soft_delete(flag, extra_updates={"active": False})


def _restore_feature_flag(viewset: "FileSystemViewSet", payload: dict[str, Any]) -> FeatureFlag:
    flag = FeatureFlag.objects.get(team=viewset.team, id=payload["ref"])
    return cast(
        FeatureFlag,
        _restore_soft_delete(flag, extra_updates={"active": True}, restore_path=payload.get("path")),
    )


def _delete_experiment(viewset: "FileSystemViewSet", entry: FileSystem) -> None:
    experiment = Experiment.objects.get(team=entry.team, id=_require_entry_ref(entry))
    _soft_delete(experiment)


def _restore_experiment(viewset: "FileSystemViewSet", payload: dict[str, Any]) -> Experiment:
    experiment = Experiment.objects.get(team=viewset.team, id=payload["ref"])
    return cast(Experiment, _restore_soft_delete(experiment, restore_path=payload.get("path")))


def _delete_insight(viewset: "FileSystemViewSet", entry: FileSystem) -> None:
    insight = Insight.objects_including_soft_deleted.get(team=entry.team, short_id=entry.ref)
    insight_name = insight.name or insight.derived_name or "Untitled insight"
    insight_id = insight.id
    insight_short_id = insight.short_id
    _soft_delete(insight)
    _log_file_system_activity(
        viewset,
        scope="Insight",
        activity="deleted",
        item_id=insight_id,
        name=insight_name,
        short_id=insight_short_id,
    )


def _restore_insight(viewset: "FileSystemViewSet", payload: dict[str, Any]) -> Insight:
    insight = Insight.objects_including_soft_deleted.get(team=viewset.team, short_id=payload["ref"])
    restored_insight = cast(Insight, _restore_soft_delete(insight, restore_path=payload.get("path")))
    _log_restore_activity(
        viewset,
        scope="Insight",
        item_id=restored_insight.id,
        name=restored_insight.name or restored_insight.derived_name or "Untitled insight",
        short_id=restored_insight.short_id,
    )
    return restored_insight


def _delete_link(viewset: "FileSystemViewSet", entry: FileSystem) -> None:
    link = Link.objects.get(team=entry.team, id=_require_entry_ref(entry))
    link_name = link.short_code or link.redirect_url or str(link.id)
    link_id = link.id
    link.delete()
    _log_file_system_activity(
        viewset,
        scope="Link",
        activity="deleted",
        item_id=link_id,
        name=link_name,
    )


def _delete_notebook(viewset: "FileSystemViewSet", entry: FileSystem) -> None:
    notebook = Notebook.objects.get(team=entry.team, short_id=_require_entry_ref(entry))
    _soft_delete(notebook)
    organization = getattr(viewset, "organization", None)
    if organization:
        log_notebook_activity(
            activity="deleted",
            notebook=notebook,
            organization_id=organization.id,
            team_id=viewset.team_id,
            user=cast(User, viewset.request.user),
            was_impersonated=is_impersonated_session(viewset.request),
        )


def _restore_notebook(viewset: "FileSystemViewSet", payload: dict[str, Any]) -> Notebook:
    notebook = Notebook.objects.get(team=viewset.team, short_id=payload["ref"])
    restored_notebook = cast(Notebook, _restore_soft_delete(notebook, restore_path=payload.get("path")))
    organization = getattr(viewset, "organization", None)
    if organization:
        log_notebook_activity(
            activity="updated",
            notebook=restored_notebook,
            organization_id=organization.id,
            team_id=viewset.team_id,
            user=cast(User, viewset.request.user),
            was_impersonated=is_impersonated_session(viewset.request),
            changes=[Change(type="Notebook", action="changed", field="deleted", before=True, after=False)],
        )
    return restored_notebook


def _delete_session_recording_playlist(viewset: "FileSystemViewSet", entry: FileSystem) -> None:
    playlist = SessionRecordingPlaylist.objects.get(team=entry.team, short_id=_require_entry_ref(entry))
    _soft_delete(playlist)
    organization = getattr(viewset, "organization", None)
    if organization:
        log_playlist_activity(
            activity="deleted",
            playlist=playlist,
            playlist_id=playlist.id,
            playlist_short_id=playlist.short_id,
            organization_id=organization.id,
            team_id=viewset.team_id,
            user=cast(User, viewset.request.user),
            was_impersonated=is_impersonated_session(viewset.request),
        )


def _restore_session_recording_playlist(
    viewset: "FileSystemViewSet", payload: dict[str, Any]
) -> SessionRecordingPlaylist:
    playlist = SessionRecordingPlaylist.objects.get(team=viewset.team, short_id=payload["ref"])
    restored_playlist = cast(
        SessionRecordingPlaylist,
        _restore_soft_delete(playlist, restore_path=payload.get("path")),
    )
    organization = getattr(viewset, "organization", None)
    if organization:
        log_playlist_activity(
            activity="updated",
            playlist=restored_playlist,
            playlist_id=restored_playlist.id,
            playlist_short_id=restored_playlist.short_id,
            organization_id=organization.id,
            team_id=viewset.team_id,
            user=cast(User, viewset.request.user),
            was_impersonated=is_impersonated_session(viewset.request),
            changes=[
                Change(
                    type="SessionRecordingPlaylist",
                    action="changed",
                    field="deleted",
                    before=True,
                    after=False,
                )
            ],
        )
    return restored_playlist


def _delete_cohort(viewset: "FileSystemViewSet", entry: FileSystem) -> None:
    cohort = Cohort.objects.get(team=entry.team, id=_require_entry_ref(entry))
    cohort_name = cohort.name or "Untitled cohort"
    cohort_id = cohort.id
    _soft_delete(cohort)
    _log_file_system_activity(
        viewset,
        scope="Cohort",
        activity="deleted",
        item_id=cohort_id,
        name=cohort_name,
    )


def _restore_cohort(viewset: "FileSystemViewSet", payload: dict[str, Any]) -> Cohort:
    cohort = Cohort.objects.get(team=viewset.team, id=payload["ref"])
    restored_cohort = cast(Cohort, _restore_soft_delete(cohort, restore_path=payload.get("path")))
    _log_restore_activity(
        viewset,
        scope="Cohort",
        item_id=restored_cohort.id,
        name=restored_cohort.name or "Untitled cohort",
    )
    return restored_cohort


def _delete_hog_function(viewset: "FileSystemViewSet", entry: FileSystem) -> None:
    hog_function = HogFunction.objects.get(team=entry.team, id=_require_entry_ref(entry))
    hog_function_name = hog_function.name or "Untitled"
    hog_function_id = hog_function.id
    _soft_delete(hog_function, extra_updates={"enabled": False})
    _log_file_system_activity(
        viewset,
        scope="HogFunction",
        activity="deleted",
        item_id=hog_function_id,
        name=hog_function_name,
    )


def _restore_hog_function(viewset: "FileSystemViewSet", payload: dict[str, Any]) -> HogFunction:
    hog_function = HogFunction.objects.get(team=viewset.team, id=payload["ref"])
    restored_hog_function = cast(
        HogFunction,
        _restore_soft_delete(hog_function, extra_updates={"enabled": True}, restore_path=payload.get("path")),
    )
    _log_restore_activity(
        viewset,
        scope="HogFunction",
        item_id=restored_hog_function.id,
        name=restored_hog_function.name or "Untitled",
        extra_changes=[Change(type="HogFunction", action="changed", field="enabled", before=False, after=True)],
    )
    return restored_hog_function


def _delete_survey(viewset: "FileSystemViewSet", entry: FileSystem) -> None:
    survey = Survey.objects.select_related("targeting_flag", "internal_targeting_flag").get(
        team=entry.team, id=_require_entry_ref(entry)
    )
    if survey.targeting_flag:
        survey.targeting_flag.delete()
    if survey.internal_targeting_flag:
        survey.internal_targeting_flag.delete()

    if hasattr(viewset, "organization") and viewset.organization:
        log_activity(
            organization_id=viewset.organization.id,
            team_id=viewset.team_id,
            user=cast(User, viewset.request.user),
            was_impersonated=is_impersonated_session(viewset.request),
            item_id=survey.id,
            scope="Survey",
            activity="deleted",
            detail=Detail(name=survey.name),
        )

    survey.delete()


def _delete_early_access_feature(viewset: "FileSystemViewSet", entry: FileSystem) -> None:
    feature = EarlyAccessFeature.objects.select_related("feature_flag").get(
        team=entry.team, id=_require_entry_ref(entry)
    )
    if feature.feature_flag:
        feature.feature_flag.filters = {
            **feature.feature_flag.filters,
            "super_groups": None,
        }
        feature.feature_flag.save(update_fields=["filters"])
    feature_name = feature.name or "Untitled feature"
    feature_id = feature.id
    feature.delete()
    _log_file_system_activity(
        viewset,
        scope="EarlyAccessFeature",
        activity="deleted",
        item_id=feature_id,
        name=feature_name,
    )


DELETE_HANDLER_MAP: dict[str, DeleteHandler] = {
    "action": DeleteHandler(
        delete=_delete_action,
        mode="soft",
        undo="Send PATCH /api/projects/@current/actions/{id} with deleted=false.",
        restore=_restore_action,
    ),
    "dashboard": DeleteHandler(
        delete=_delete_dashboard,
        mode="soft",
        undo="Send PATCH /api/projects/@current/dashboards/{id} with deleted=false.",
        restore=_restore_dashboard,
    ),
    "feature_flag": DeleteHandler(
        delete=_delete_feature_flag,
        mode="soft",
        undo="Send PATCH /api/projects/@current/feature_flags/{id} with deleted=false.",
        restore=_restore_feature_flag,
    ),
    "experiment": DeleteHandler(
        delete=_delete_experiment,
        mode="soft",
        undo="Send PATCH /api/projects/@current/experiments/{id} with deleted=false.",
        restore=_restore_experiment,
    ),
    "insight": DeleteHandler(
        delete=_delete_insight,
        mode="soft",
        undo="Send PATCH /api/projects/@current/insights/{id} with deleted=false.",
        restore=_restore_insight,
    ),
    "link": DeleteHandler(
        delete=_delete_link,
        mode="hard",
        undo="Create a new link with the same details.",
    ),
    "notebook": DeleteHandler(
        delete=_delete_notebook,
        mode="soft",
        undo="Send PATCH /api/projects/@current/notebooks/{id} with deleted=false.",
        restore=_restore_notebook,
    ),
    "session_recording_playlist": DeleteHandler(
        delete=_delete_session_recording_playlist,
        mode="soft",
        undo="Send PATCH /api/projects/@current/session_recordings/playlists/{id} with deleted=false.",
        restore=_restore_session_recording_playlist,
    ),
    "cohort": DeleteHandler(
        delete=_delete_cohort,
        mode="soft",
        undo="Send PATCH /api/projects/@current/cohorts/{id} with deleted=false.",
        restore=_restore_cohort,
    ),
    "survey": DeleteHandler(
        delete=_delete_survey,
        mode="hard",
        undo="Create a new survey using the saved configuration.",
    ),
    "early_access_feature": DeleteHandler(
        delete=_delete_early_access_feature,
        mode="hard",
        undo="Recreate the early access feature and reapply any filters.",
    ),
}

PREFIX_DELETE_HANDLERS: list[tuple[str, DeleteHandler]] = [
    (
        "hog_function/",
        DeleteHandler(
            delete=_delete_hog_function,
            mode="soft",
            undo="Send PATCH /api/projects/@current/hog_functions/{id} with deleted=false.",
            restore=_restore_hog_function,
        ),
    ),
]


def _get_delete_handler(file_type: str | None) -> DeleteHandler | None:
    if not file_type:
        return None
    handler = DELETE_HANDLER_MAP.get(file_type)
    if handler:
        return handler
    for prefix, prefixed_handler in PREFIX_DELETE_HANDLERS:
        if file_type.startswith(prefix):
            return prefixed_handler
    return None


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

            handler = _get_delete_handler(current.type)

            if handler is None:
                continue

            if remaining == 0 and not current.ref:
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

        handler = _get_delete_handler(entry.type)
        if handler is None:
            entry.delete()
            return deleted_objects

        if remaining > 0:
            entry.delete()
            return deleted_objects

        if not entry.ref:
            raise serializers.ValidationError({"detail": f"Cannot delete type '{entry.type}' without a reference."})

        handler.delete(self, entry)

        # Ensure the original FileSystem entry is gone even if signals haven't run yet
        entry_id = entry.id
        if entry_id is not None:
            FileSystem.objects.filter(id=entry_id).delete()

        deleted_objects.append(
            {
                "type": entry.type,
                "ref": entry.ref,
                "mode": handler.mode,
                "undo": handler.undo,
                "path": entry.path,
                "can_undo": handler.restore is not None,
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
                handler = _get_delete_handler(item["type"])
                if handler is None or handler.restore is None:
                    raise serializers.ValidationError({"detail": f"Undo for type '{item['type']}' is not supported."})
                restored_instance = handler.restore(self, item)
                self._restore_file_system_path(restored_instance, item)
                undo_results.append({"type": item["type"], "ref": item["ref"]})

        return Response({"undone": undo_results}, status=status.HTTP_200_OK)

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

        update_count = FileSystem.objects.filter(team=team, type=payload["type"], ref=payload["ref"]).update(
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
