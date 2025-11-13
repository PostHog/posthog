from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Optional, cast

from django.apps import apps

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.activity_logging.model_activity import is_impersonated_session
from posthog.models.file_system.file_system import FileSystem, join_path, split_path
from posthog.models.user import User
from posthog.session_recordings.session_recording_playlist_api import log_playlist_activity

from products.notebooks.backend.api.notebook import log_notebook_activity

if TYPE_CHECKING:
    from posthog.api.file_system.file_system import FileSystemViewSet


HOG_FUNCTION_TYPES = ["broadcast", "campaign", "destination", "site_app", "source", "transformation"]


@dataclass(frozen=True)
class DeleteHandler:
    delete: Callable[[FileSystemViewSet, FileSystem], None]
    mode: Literal["soft", "hard"]
    undo: str
    restore: Optional[Callable[[FileSystemViewSet, dict[str, Any]], Any]] = None


@dataclass(frozen=True)
class DeleteContext:
    viewset: FileSystemViewSet
    entry: FileSystem
    user: Optional[User]

    @property
    def organization(self):
        return getattr(self.viewset, "organization", None)


@dataclass(frozen=True)
class RestoreContext:
    viewset: FileSystemViewSet
    payload: dict[str, Any]
    user: Optional[User]

    @property
    def organization(self):
        return getattr(self.viewset, "organization", None)


@dataclass(frozen=True)
class ModelConfig:
    app_label: str
    model_name: str
    lookup_field: str = "id"
    manager_name: str = "objects"
    team_field: str = "team"
    queryset_modifier: Callable[[Any], Any] | None = None
    delete_updates: Callable[[Any], dict[str, Any]] | dict[str, Any] | None = None
    restore_updates: Callable[[Any], dict[str, Any]] | dict[str, Any] | None = None
    soft_delete_field: str = "deleted"
    allow_restore: bool = True
    pre_delete_hook: Callable[[DeleteContext, Any], None] | None = None
    post_delete_hook: Callable[[DeleteContext, Any], None] | None = None
    pre_restore_hook: Callable[[RestoreContext, Any], None] | None = None
    post_restore_hook: Callable[[RestoreContext, Any], Any] | None = None
    hard_delete_override: Optional[bool] = None


@dataclass(frozen=True)
class HandlerConfig:
    model: ModelConfig
    undo: str


def _get_request_user(viewset: FileSystemViewSet) -> Optional[User]:
    request_user = getattr(viewset.request, "user", None)
    if request_user and getattr(request_user, "is_authenticated", False):
        return cast(User, request_user)
    return None


def _set_last_modified_by(instance: Any, user: Optional[User], update_fields: list[str]) -> None:
    if not user or not getattr(user, "is_authenticated", False):
        return

    if not hasattr(instance, "last_modified_by"):
        return

    current_id = getattr(instance, "last_modified_by_id", None)
    instance.last_modified_by = user

    if current_id != user.id and "last_modified_by" not in update_fields:
        update_fields.append("last_modified_by")


def _soft_delete(
    instance: Any,
    *,
    field: str = "deleted",
    extra_updates: Optional[dict[str, Any]] = None,
    user: Optional[User] = None,
) -> None:
    update_fields: list[str] = []
    if extra_updates:
        for attr, value in extra_updates.items():
            if getattr(instance, attr) != value:
                setattr(instance, attr, value)
                update_fields.append(attr)
    if getattr(instance, field) is not True:
        setattr(instance, field, True)
        update_fields.append(field)

    _set_last_modified_by(instance, user, update_fields)

    if update_fields:
        instance.save(update_fields=update_fields)
    else:
        instance.save()


def _restore_soft_delete(
    instance: Any,
    *,
    field: str = "deleted",
    extra_updates: Optional[dict[str, Any]] = None,
    restore_path: Optional[str] = None,
    user: Optional[User] = None,
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

    _set_last_modified_by(instance, user, update_fields)

    if update_fields:
        instance.save(update_fields=update_fields)
    else:
        instance.save()
    return instance


def _resolve_updates(updates: Callable[[Any], dict[str, Any]] | dict[str, Any] | None, instance: Any) -> dict[str, Any]:
    if updates is None:
        return {}
    if callable(updates):
        return updates(instance)
    return updates


def _apply_updates(instance: Any, updates: dict[str, Any], user: Optional[User]) -> None:
    if not updates:
        return

    update_fields: list[str] = []
    for attr, value in updates.items():
        if getattr(instance, attr) != value:
            setattr(instance, attr, value)
            update_fields.append(attr)

    _set_last_modified_by(instance, user, update_fields)

    if update_fields:
        instance.save(update_fields=update_fields)
    else:
        instance.save()


def _log_file_system_activity(
    viewset: FileSystemViewSet,
    *,
    scope: str,
    activity: Literal["deleted", "updated", "restored"],
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
    viewset: FileSystemViewSet,
    *,
    scope: str,
    item_id: str | int,
    name: Optional[str] = None,
    short_id: Optional[str] = None,
    extra_changes: Optional[list[Change]] = None,
) -> None:
    changes = list(extra_changes or [])
    changes.append(Change(type=scope, action="changed", field="deleted", before=True, after=False))
    _log_file_system_activity(
        viewset,
        scope=scope,
        activity="restored",
        item_id=item_id,
        name=name,
        short_id=short_id,
        changes=changes,
    )


def _get_model_class(model_config: ModelConfig):
    return apps.get_model(model_config.app_label, model_config.model_name)


def _get_queryset(model_class: Any, model_config: ModelConfig):
    manager = getattr(model_class, model_config.manager_name)
    queryset = manager.all()
    if model_config.queryset_modifier:
        queryset = model_config.queryset_modifier(queryset)
    return queryset


def _get_object_for_entry(model_config: ModelConfig, entry: FileSystem):
    model_class = _get_model_class(model_config)
    queryset = _get_queryset(model_class, model_config)
    filters: dict[str, Any] = {model_config.lookup_field: entry.ref}
    if model_config.team_field:
        filters[model_config.team_field] = entry.team_id
    return queryset.get(**filters)


def _get_object_for_restore(model_config: ModelConfig, viewset: FileSystemViewSet, payload: dict[str, Any]):
    model_class = _get_model_class(model_config)
    queryset = _get_queryset(model_class, model_config)
    filters: dict[str, Any] = {model_config.lookup_field: payload["ref"]}
    if model_config.team_field:
        filters[model_config.team_field] = viewset.team_id
    return queryset.get(**filters)


def _supports_soft_delete(model_config: ModelConfig) -> bool:
    if model_config.hard_delete_override is True:
        return False
    if model_config.hard_delete_override is False:
        return True
    model_class = _get_model_class(model_config)
    return any(field.name == model_config.soft_delete_field for field in model_class._meta.fields)


def _build_delete_handler(config: HandlerConfig) -> DeleteHandler:
    supports_soft_delete = _supports_soft_delete(config.model)

    def delete(viewset: FileSystemViewSet, entry: FileSystem) -> None:
        context = DeleteContext(viewset=viewset, entry=entry, user=_get_request_user(viewset))
        instance = _get_object_for_entry(config.model, entry)

        if config.model.pre_delete_hook:
            config.model.pre_delete_hook(context, instance)

        if supports_soft_delete:
            updates = _resolve_updates(config.model.delete_updates, instance)
            _soft_delete(
                instance,
                field=config.model.soft_delete_field,
                extra_updates=updates,
                user=context.user,
            )
        else:
            updates = _resolve_updates(config.model.delete_updates, instance)
            _apply_updates(instance, updates, context.user)
            instance.delete()

        if config.model.post_delete_hook:
            config.model.post_delete_hook(context, instance)

    restore: Optional[Callable[[FileSystemViewSet, dict[str, Any]], Any]] = None

    if supports_soft_delete and config.model.allow_restore:

        def restore(viewset: FileSystemViewSet, payload: dict[str, Any]) -> Any:
            context = RestoreContext(viewset=viewset, payload=payload, user=_get_request_user(viewset))
            instance = _get_object_for_restore(config.model, viewset, payload)

            if config.model.pre_restore_hook:
                config.model.pre_restore_hook(context, instance)

            updates = _resolve_updates(config.model.restore_updates, instance)
            restored = _restore_soft_delete(
                instance,
                field=config.model.soft_delete_field,
                extra_updates=updates,
                restore_path=payload.get("path"),
                user=context.user,
            )

            if config.model.post_restore_hook:
                result = config.model.post_restore_hook(context, restored)
                if result is not None:
                    return result
            return restored

        restore_callable = restore
    else:
        restore_callable = None

    mode: Literal["soft", "hard"] = "soft" if supports_soft_delete else "hard"
    return DeleteHandler(delete=delete, mode=mode, undo=config.undo, restore=restore_callable)


def _dashboard_post_restore(context: RestoreContext, dashboard: Any) -> None:
    _log_restore_activity(
        context.viewset,
        scope="Dashboard",
        item_id=dashboard.id,
        name=dashboard.name or "Untitled dashboard",
    )


def _dashboard_post_delete(context: DeleteContext, dashboard: Any) -> None:
    _log_file_system_activity(
        context.viewset,
        scope="Dashboard",
        activity="deleted",
        item_id=dashboard.id,
        name=dashboard.name or "Untitled dashboard",
    )


def _experiment_post_restore(context: RestoreContext, experiment: Any) -> None:
    _log_restore_activity(
        context.viewset,
        scope="Experiment",
        item_id=experiment.id,
        name=experiment.name or "Untitled experiment",
    )


def _insight_post_delete(context: DeleteContext, insight: Any) -> None:
    _log_file_system_activity(
        context.viewset,
        scope="Insight",
        activity="deleted",
        item_id=insight.id,
        name=insight.name or getattr(insight, "derived_name", None) or "Untitled insight",
        short_id=insight.short_id,
    )


def _insight_post_restore(context: RestoreContext, insight: Any) -> None:
    _log_restore_activity(
        context.viewset,
        scope="Insight",
        item_id=insight.id,
        name=insight.name or getattr(insight, "derived_name", None) or "Untitled insight",
        short_id=insight.short_id,
    )


def _link_post_delete(context: DeleteContext, link: Any) -> None:
    ref = context.entry.ref
    if ref is None:
        return
    link_name = getattr(link, "short_code", None) or getattr(link, "redirect_url", None) or ref
    _log_file_system_activity(
        context.viewset,
        scope="Link",
        activity="deleted",
        item_id=ref,
        name=link_name,
    )


def _notebook_post_delete(context: DeleteContext, notebook: Any) -> None:
    organization = context.organization
    if not organization:
        return
    log_notebook_activity(
        activity="deleted",
        notebook=notebook,
        organization_id=organization.id,
        team_id=context.viewset.team_id,
        user=cast(User, context.viewset.request.user),
        was_impersonated=is_impersonated_session(context.viewset.request),
    )


def _notebook_post_restore(context: RestoreContext, notebook: Any) -> None:
    organization = context.organization
    if not organization:
        return
    log_notebook_activity(
        activity="restored",
        notebook=notebook,
        organization_id=organization.id,
        team_id=context.viewset.team_id,
        user=cast(User, context.viewset.request.user),
        was_impersonated=is_impersonated_session(context.viewset.request),
        changes=[Change(type="Notebook", action="changed", field="deleted", before=True, after=False)],
    )


def _playlist_post_delete(context: DeleteContext, playlist: Any) -> None:
    organization = context.organization
    if not organization:
        return
    log_playlist_activity(
        activity="deleted",
        playlist=playlist,
        playlist_id=playlist.id,
        playlist_short_id=playlist.short_id,
        organization_id=organization.id,
        team_id=context.viewset.team_id,
        user=cast(User, context.viewset.request.user),
        was_impersonated=is_impersonated_session(context.viewset.request),
    )


def _playlist_post_restore(context: RestoreContext, playlist: Any) -> None:
    organization = context.organization
    if not organization:
        return
    log_playlist_activity(
        activity="restored",
        playlist=playlist,
        playlist_id=playlist.id,
        playlist_short_id=playlist.short_id,
        organization_id=organization.id,
        team_id=context.viewset.team_id,
        user=cast(User, context.viewset.request.user),
        was_impersonated=is_impersonated_session(context.viewset.request),
        changes=[Change(type="SessionRecordingPlaylist", action="changed", field="deleted", before=True, after=False)],
    )


def _cohort_post_delete(context: DeleteContext, cohort: Any) -> None:
    _log_file_system_activity(
        context.viewset,
        scope="Cohort",
        activity="deleted",
        item_id=cohort.id,
        name=cohort.name or "Untitled cohort",
    )


def _cohort_post_restore(context: RestoreContext, cohort: Any) -> None:
    _log_restore_activity(
        context.viewset,
        scope="Cohort",
        item_id=cohort.id,
        name=cohort.name or "Untitled cohort",
    )


def _hog_function_post_delete(context: DeleteContext, hog_function: Any) -> None:
    _log_file_system_activity(
        context.viewset,
        scope="HogFunction",
        activity="deleted",
        item_id=hog_function.id,
        name=hog_function.name or "Untitled",
    )


def _hog_function_post_restore(context: RestoreContext, hog_function: Any) -> None:
    _log_restore_activity(
        context.viewset,
        scope="HogFunction",
        item_id=hog_function.id,
        name=hog_function.name or "Untitled",
        extra_changes=[Change(type="HogFunction", action="changed", field="enabled", before=False, after=True)],
    )


def _survey_pre_delete(context: DeleteContext, survey: Any) -> None:
    targeting_flag = getattr(survey, "targeting_flag", None)
    if targeting_flag:
        targeting_flag.delete()
    internal_targeting_flag = getattr(survey, "internal_targeting_flag", None)
    if internal_targeting_flag:
        internal_targeting_flag.delete()


def _survey_post_delete(context: DeleteContext, survey: Any) -> None:
    organization = context.organization
    if not organization:
        return
    ref = context.entry.ref
    if ref is None:
        return
    log_activity(
        organization_id=organization.id,
        team_id=context.viewset.team_id,
        user=cast(User, context.viewset.request.user),
        was_impersonated=is_impersonated_session(context.viewset.request),
        item_id=ref,
        scope="Survey",
        activity="deleted",
        detail=Detail(name=survey.name),
    )


def _early_access_feature_pre_delete(context: DeleteContext, feature: Any) -> None:
    feature_flag = getattr(feature, "feature_flag", None)
    if feature_flag:
        filters = dict(feature_flag.filters or {})
        filters["super_groups"] = None
        feature_flag.filters = filters
        feature_flag.save(update_fields=["filters"])


def _early_access_feature_post_delete(context: DeleteContext, feature: Any) -> None:
    ref = context.entry.ref
    if ref is None:
        return
    _log_file_system_activity(
        context.viewset,
        scope="EarlyAccessFeature",
        activity="deleted",
        item_id=ref,
        name=feature.name or "Untitled feature",
    )


MODEL_CONFIGS: dict[str, ModelConfig] = {
    "action": ModelConfig(app_label="posthog", model_name="Action"),
    "dashboard": ModelConfig(
        app_label="posthog",
        model_name="Dashboard",
        manager_name="objects_including_soft_deleted",
        post_delete_hook=_dashboard_post_delete,
        post_restore_hook=_dashboard_post_restore,
    ),
    "feature_flag": ModelConfig(
        app_label="posthog",
        model_name="FeatureFlag",
        delete_updates={"active": False},
        restore_updates={"active": True},
    ),
    "experiment": ModelConfig(
        app_label="posthog",
        model_name="Experiment",
        post_restore_hook=_experiment_post_restore,
    ),
    "insight": ModelConfig(
        app_label="posthog",
        model_name="Insight",
        manager_name="objects_including_soft_deleted",
        lookup_field="short_id",
        post_delete_hook=_insight_post_delete,
        post_restore_hook=_insight_post_restore,
    ),
    "link": ModelConfig(
        app_label="posthog",
        model_name="Link",
        allow_restore=False,
        post_delete_hook=_link_post_delete,
    ),
    "notebook": ModelConfig(
        app_label="notebooks",
        model_name="Notebook",
        lookup_field="short_id",
        post_delete_hook=_notebook_post_delete,
        post_restore_hook=_notebook_post_restore,
    ),
    "session_recording_playlist": ModelConfig(
        app_label="posthog",
        model_name="SessionRecordingPlaylist",
        lookup_field="short_id",
        post_delete_hook=_playlist_post_delete,
        post_restore_hook=_playlist_post_restore,
    ),
    "cohort": ModelConfig(
        app_label="posthog",
        model_name="Cohort",
        post_delete_hook=_cohort_post_delete,
        post_restore_hook=_cohort_post_restore,
    ),
    "survey": ModelConfig(
        app_label="posthog",
        model_name="Survey",
        queryset_modifier=lambda qs: qs.select_related("targeting_flag", "internal_targeting_flag"),
        hard_delete_override=True,
        allow_restore=False,
        pre_delete_hook=_survey_pre_delete,
        post_delete_hook=_survey_post_delete,
    ),
    "early_access_feature": ModelConfig(
        app_label="early_access_features",
        model_name="EarlyAccessFeature",
        queryset_modifier=lambda qs: qs.select_related("feature_flag"),
        hard_delete_override=True,
        allow_restore=False,
        pre_delete_hook=_early_access_feature_pre_delete,
        post_delete_hook=_early_access_feature_post_delete,
    ),
}


_hog_function_config = ModelConfig(
    app_label="posthog",
    model_name="HogFunction",
    delete_updates={"enabled": False},
    restore_updates={"enabled": True},
    post_delete_hook=_hog_function_post_delete,
    post_restore_hook=_hog_function_post_restore,
)


for hog_type in HOG_FUNCTION_TYPES:
    MODEL_CONFIGS[f"hog_function/{hog_type}"] = _hog_function_config


HANDLER_CONFIGS: dict[str, HandlerConfig] = {
    "action": HandlerConfig(
        model=MODEL_CONFIGS["action"],
        undo="Send PATCH /api/projects/@current/actions/{id} with deleted=false.",
    ),
    "dashboard": HandlerConfig(
        model=MODEL_CONFIGS["dashboard"],
        undo="Send PATCH /api/projects/@current/dashboards/{id} with deleted=false.",
    ),
    "feature_flag": HandlerConfig(
        model=MODEL_CONFIGS["feature_flag"],
        undo="Send PATCH /api/projects/@current/feature_flags/{id} with deleted=false.",
    ),
    "experiment": HandlerConfig(
        model=MODEL_CONFIGS["experiment"],
        undo="Send PATCH /api/projects/@current/experiments/{id} with deleted=false.",
    ),
    "insight": HandlerConfig(
        model=MODEL_CONFIGS["insight"],
        undo="Send PATCH /api/projects/@current/insights/{id} with deleted=false.",
    ),
    "link": HandlerConfig(
        model=MODEL_CONFIGS["link"],
        undo="Create a new link with the same details.",
    ),
    "notebook": HandlerConfig(
        model=MODEL_CONFIGS["notebook"],
        undo="Send PATCH /api/projects/@current/notebooks/{id} with deleted=false.",
    ),
    "session_recording_playlist": HandlerConfig(
        model=MODEL_CONFIGS["session_recording_playlist"],
        undo="Send PATCH /api/projects/@current/session_recordings/playlists/{id} with deleted=false.",
    ),
    "cohort": HandlerConfig(
        model=MODEL_CONFIGS["cohort"],
        undo="Send PATCH /api/projects/@current/cohorts/{id} with deleted=false.",
    ),
    "survey": HandlerConfig(
        model=MODEL_CONFIGS["survey"],
        undo="Create a new survey using the saved configuration.",
    ),
    "early_access_feature": HandlerConfig(
        model=MODEL_CONFIGS["early_access_feature"],
        undo="Recreate the early access feature and reapply any filters.",
    ),
}


for hog_type in HOG_FUNCTION_TYPES:
    HANDLER_CONFIGS[f"hog_function/{hog_type}"] = HandlerConfig(
        model=MODEL_CONFIGS[f"hog_function/{hog_type}"],
        undo="Send PATCH /api/projects/@current/hog_functions/{id} with deleted=false.",
    )


DELETE_HANDLER_MAP: dict[str, DeleteHandler] = {
    key: _build_delete_handler(config) for key, config in HANDLER_CONFIGS.items()
}


MODEL_MAP: dict[str, tuple[str, str]] = {
    key: (config.model.app_label, config.model.model_name) for key, config in HANDLER_CONFIGS.items()
}


def get_delete_handler(file_type: str | None) -> Optional[DeleteHandler]:
    if not file_type:
        return None
    return DELETE_HANDLER_MAP.get(file_type)
