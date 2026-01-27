from __future__ import annotations

from typing import Any

from posthog.api.file_system.deletion import (
    HOG_FUNCTION_TYPES,
    DeletionContext,
    RestoreContext,
    register_file_system_type,
    register_post_delete_hook,
    register_post_restore_hook,
    register_pre_delete_hook,
    register_pre_restore_hook,
)
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.activity_logging.model_activity import is_impersonated_session
from posthog.models.hog_functions.utils import humanize_hog_function_type
from posthog.models.user import User
from posthog.session_recordings.session_recording_playlist_api import log_playlist_activity


def _first_non_blank(*values: str | None) -> str | None:
    for value in values:
        if value is None:
            continue
        candidate = value.strip()
        if candidate:
            return candidate
    return None


def _log_deletion_activity(
    context: DeletionContext,
    *,
    scope: str,
    item_id: Any,
    name: str | None = None,
    short_id: str | None = None,
    object_type: str | None = None,
    changes: list[Change] | None = None,
) -> None:
    organization = context.organization
    if not organization:
        return

    team_id = getattr(context.team, "id", None)
    display_name = _first_non_blank(name, short_id, object_type) or scope
    log_activity(
        organization_id=organization.id,
        team_id=team_id,
        user=context.user,
        was_impersonated=is_impersonated_session(context.request) if context.request else False,
        item_id=str(item_id),
        scope=scope,
        activity="deleted",
        detail=Detail(name=display_name, short_id=short_id, type=object_type, changes=changes),
    )


def _log_restore_activity(
    context: RestoreContext,
    *,
    scope: str,
    item_id: Any,
    name: str | None = None,
    short_id: str | None = None,
    object_type: str | None = None,
    extra_changes: list[Change] | None = None,
) -> None:
    organization = context.organization
    if not organization:
        return

    team_id = getattr(context.team, "id", None)
    changes = list(extra_changes or [])
    changes.append(Change(type=scope, action="changed", field="deleted", before=True, after=False))
    display_name = _first_non_blank(name, short_id, object_type) or scope
    log_activity(
        organization_id=organization.id,
        team_id=team_id,
        user=context.user,
        was_impersonated=is_impersonated_session(context.request) if context.request else False,
        item_id=str(item_id),
        scope=scope,
        activity="restored",
        detail=Detail(name=display_name, short_id=short_id, type=object_type, changes=changes),
    )


def _dashboard_post_delete(context: DeletionContext, dashboard: Any) -> None:
    _log_deletion_activity(
        context,
        scope="Dashboard",
        item_id=dashboard.id,
        name=_first_non_blank(getattr(dashboard, "name", None)) or "Untitled dashboard",
        object_type="dashboard",
    )


def _dashboard_post_restore(context: RestoreContext, dashboard: Any) -> None:
    _log_restore_activity(
        context,
        scope="Dashboard",
        item_id=dashboard.id,
        name=_first_non_blank(getattr(dashboard, "name", None)) or "Untitled dashboard",
        object_type="dashboard",
    )


def _experiment_post_restore(context: RestoreContext, experiment: Any) -> None:
    _log_restore_activity(
        context,
        scope="Experiment",
        item_id=experiment.id,
        name=_first_non_blank(getattr(experiment, "name", None)) or "Untitled experiment",
        object_type="experiment",
    )


def _experiment_post_delete(context: DeletionContext, experiment: Any) -> None:
    _log_deletion_activity(
        context,
        scope="Experiment",
        item_id=experiment.id,
        name=_first_non_blank(getattr(experiment, "name", None)) or "Untitled experiment",
        object_type="experiment",
    )


def _insight_post_delete(context: DeletionContext, insight: Any) -> None:
    _log_deletion_activity(
        context,
        scope="Insight",
        item_id=insight.id,
        name=_first_non_blank(getattr(insight, "name", None), getattr(insight, "derived_name", None))
        or "Untitled insight",
        short_id=getattr(insight, "short_id", None),
        object_type="insight",
    )


def _insight_post_restore(context: RestoreContext, insight: Any) -> None:
    _log_restore_activity(
        context,
        scope="Insight",
        item_id=insight.id,
        name=_first_non_blank(getattr(insight, "name", None), getattr(insight, "derived_name", None))
        or "Untitled insight",
        short_id=getattr(insight, "short_id", None),
        object_type="insight",
    )


def _link_post_delete(context: DeletionContext, link: Any) -> None:
    ref = context.entry.ref
    link_name = getattr(link, "short_code", None) or getattr(link, "redirect_url", None) or ref
    _log_deletion_activity(
        context,
        scope="Link",
        item_id=ref,
        name=link_name,
    )


def _playlist_post_restore(context: RestoreContext, playlist: Any) -> None:
    organization = context.organization
    if not organization:
        return
    team = context.team
    team_id = getattr(team, "id", None) if team is not None else None
    if not isinstance(team_id, int):
        return
    user = context.user
    if not isinstance(user, User):
        return
    short_id = getattr(playlist, "short_id", None)
    if short_id is None:
        return
    log_playlist_activity(
        activity="restored",
        playlist=playlist,
        playlist_id=playlist.id,
        playlist_short_id=str(short_id),
        organization_id=organization.id,
        team_id=team_id,
        user=user,
        was_impersonated=is_impersonated_session(context.request) if context.request else False,
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


def _playlist_post_delete(context: DeletionContext, playlist: Any) -> None:
    organization = context.organization
    if not organization:
        return

    team = context.team
    team_id = getattr(team, "id", None) if team is not None else None
    if not isinstance(team_id, int):
        return

    user = context.user
    if not isinstance(user, User):
        return

    short_id = getattr(playlist, "short_id", None)
    if short_id is None:
        return

    log_playlist_activity(
        activity="deleted",
        playlist=playlist,
        playlist_id=playlist.id,
        playlist_short_id=str(short_id),
        organization_id=organization.id,
        team_id=team_id,
        user=user,
        was_impersonated=is_impersonated_session(context.request) if context.request else False,
        changes=[
            Change(
                type="SessionRecordingPlaylist",
                action="changed",
                field="deleted",
                before=False,
                after=True,
            )
        ],
    )


def _cohort_post_delete(context: DeletionContext, cohort: Any) -> None:
    _log_deletion_activity(
        context,
        scope="Cohort",
        item_id=cohort.id,
        name=_first_non_blank(getattr(cohort, "name", None)) or "Untitled cohort",
        object_type="cohort",
    )


def _cohort_post_restore(context: RestoreContext, cohort: Any) -> None:
    _log_restore_activity(
        context,
        scope="Cohort",
        item_id=cohort.id,
        name=_first_non_blank(getattr(cohort, "name", None)) or "Untitled cohort",
        object_type="cohort",
    )


def _action_post_delete(context: DeletionContext, action: Any) -> None:
    _log_deletion_activity(
        context,
        scope="Action",
        item_id=action.id,
        name=_first_non_blank(getattr(action, "name", None)) or "Untitled action",
        object_type="action",
    )


def _action_post_restore(context: RestoreContext, action: Any) -> None:
    _log_restore_activity(
        context,
        scope="Action",
        item_id=action.id,
        name=_first_non_blank(getattr(action, "name", None)) or "Untitled action",
        object_type="action",
    )


def _hog_function_pre_delete(context: DeletionContext, hog_function: Any) -> None:
    hog_function.enabled = False


def _hog_function_pre_restore(context: RestoreContext, hog_function: Any) -> None:
    hog_function.enabled = True


def _hog_function_post_delete(context: DeletionContext, hog_function: Any) -> None:
    _log_deletion_activity(
        context,
        scope="HogFunction",
        item_id=hog_function.id,
        name=_first_non_blank(getattr(hog_function, "name", None)) or "Untitled",
        object_type=humanize_hog_function_type(getattr(hog_function, "type", None)),
    )


def _hog_function_post_restore(context: RestoreContext, hog_function: Any) -> None:
    _log_restore_activity(
        context,
        scope="HogFunction",
        item_id=hog_function.id,
        name=_first_non_blank(getattr(hog_function, "name", None)) or "Untitled",
        object_type=humanize_hog_function_type(getattr(hog_function, "type", None)),
        extra_changes=[Change(type="HogFunction", action="changed", field="enabled", before=False, after=True)],
    )


def _feature_flag_post_delete(context: DeletionContext, feature_flag: Any) -> None:
    _log_deletion_activity(
        context,
        scope="FeatureFlag",
        item_id=feature_flag.id,
        name=_first_non_blank(getattr(feature_flag, "name", None), getattr(feature_flag, "key", None))
        or "Untitled feature flag",
        object_type="feature flag",
    )


def _feature_flag_post_restore(context: RestoreContext, feature_flag: Any) -> None:
    _log_restore_activity(
        context,
        scope="FeatureFlag",
        item_id=feature_flag.id,
        name=_first_non_blank(getattr(feature_flag, "name", None), getattr(feature_flag, "key", None))
        or "Untitled feature flag",
        object_type="feature flag",
        extra_changes=[Change(type="FeatureFlag", action="changed", field="active", before=False, after=True)],
    )


def _feature_flag_pre_delete(context: DeletionContext, feature_flag: Any) -> None:
    feature_flag.active = False


def _feature_flag_pre_restore(context: RestoreContext, feature_flag: Any) -> None:
    feature_flag.active = True


def register_core_file_system_types() -> None:
    register_file_system_type(
        "action",
        "posthog",
        "Action",
        undo_message="Send PATCH /api/projects/@current/actions/{id} with deleted=false.",
    )
    register_post_delete_hook("action", _action_post_delete)
    register_post_restore_hook("action", _action_post_restore)

    register_file_system_type(
        "dashboard",
        "posthog",
        "Dashboard",
        undo_message="Send PATCH /api/projects/@current/dashboards/{id} with deleted=false.",
    )
    register_post_delete_hook("dashboard", _dashboard_post_delete)
    register_post_restore_hook("dashboard", _dashboard_post_restore)

    register_file_system_type(
        "feature_flag",
        "posthog",
        "FeatureFlag",
        undo_message="Send PATCH /api/projects/@current/feature_flags/{id} with deleted=false.",
    )
    register_pre_delete_hook("feature_flag", _feature_flag_pre_delete)
    register_pre_restore_hook("feature_flag", _feature_flag_pre_restore)
    register_post_delete_hook("feature_flag", _feature_flag_post_delete)
    register_post_restore_hook("feature_flag", _feature_flag_post_restore)

    register_file_system_type(
        "experiment",
        "posthog",
        "Experiment",
        undo_message="Send PATCH /api/projects/@current/experiments/{id} with deleted=false.",
    )
    register_post_delete_hook("experiment", _experiment_post_delete)
    register_post_restore_hook("experiment", _experiment_post_restore)

    register_file_system_type(
        "insight",
        "posthog",
        "Insight",
        lookup_field="short_id",
        undo_message="Send PATCH /api/projects/@current/insights/{id} with deleted=false.",
    )
    register_post_delete_hook("insight", _insight_post_delete)
    register_post_restore_hook("insight", _insight_post_restore)

    register_file_system_type(
        "link",
        "posthog",
        "Link",
        allow_restore=False,
        undo_message="Create a new link with the same details.",
    )
    register_post_delete_hook("link", _link_post_delete)

    register_file_system_type(
        "session_recording_playlist",
        "posthog",
        "SessionRecordingPlaylist",
        lookup_field="short_id",
        undo_message="Send PATCH /api/projects/@current/session_recordings/playlists/{id} with deleted=false.",
    )
    register_post_delete_hook("session_recording_playlist", _playlist_post_delete)
    register_post_restore_hook("session_recording_playlist", _playlist_post_restore)

    register_file_system_type(
        "cohort",
        "posthog",
        "Cohort",
        undo_message="Send PATCH /api/projects/@current/cohorts/{id} with deleted=false.",
    )
    register_post_delete_hook("cohort", _cohort_post_delete)
    register_post_restore_hook("cohort", _cohort_post_restore)

    for hog_type in HOG_FUNCTION_TYPES:
        type_string = f"hog_function/{hog_type}"
        register_file_system_type(
            type_string,
            "posthog",
            "HogFunction",
            undo_message="Send PATCH /api/projects/@current/hog_functions/{id} with deleted=false.",
        )
        register_pre_delete_hook(type_string, _hog_function_pre_delete)
        register_pre_restore_hook(type_string, _hog_function_pre_restore)
        register_post_delete_hook(type_string, _hog_function_post_delete)
        register_post_restore_hook(type_string, _hog_function_post_restore)
