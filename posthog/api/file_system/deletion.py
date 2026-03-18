from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist

from posthog.models.file_system.file_system import FileSystem, join_path, split_path
from posthog.models.hog_functions.hog_function import HogFunctionType
from posthog.models.signals import mute_selected_signals

logger = logging.getLogger(__name__)

LEGACY_HOG_FUNCTION_TYPES = [
    "broadcast",
    "campaign",
    "source",
]
HOG_FUNCTION_TYPES = sorted(set(LEGACY_HOG_FUNCTION_TYPES + list(HogFunctionType.values)))


@dataclass(frozen=True)
class ModelRegistration:
    app_label: str
    model_name: str
    lookup_field: str
    manager_name: str
    team_field: str  # Required
    queryset_modifier: Callable[[Any], Any] | None
    soft_delete_field: str | None
    hard_delete: bool | None
    allow_restore: bool | None
    undo_message: str


@dataclass(frozen=True)
class ModelCapabilities:
    soft_delete_field: str | None
    has_last_modified_by: bool
    can_restore: bool

    @property
    def has_soft_delete(self) -> bool:
        return self.soft_delete_field is not None


@dataclass(frozen=True)
class DeletionResult:
    type: str
    ref: str | None
    mode: Literal["soft", "hard"]
    can_undo: bool
    undo: str


@dataclass(frozen=True)
class DeletionContext:
    entry: FileSystem
    user: Any | None
    request: Any | None
    team: Any | None
    organization: Any | None


@dataclass(frozen=True)
class RestoreContext:
    type: str
    ref: str
    restore_path: str | None
    user: Any | None
    request: Any | None
    team: Any | None
    organization: Any | None


PreDeleteHook = Callable[[DeletionContext, Any], None]
PostDeleteHook = Callable[[DeletionContext, Any], None]
PreRestoreHook = Callable[[RestoreContext, Any], None]
PostRestoreHook = Callable[[RestoreContext, Any], None]

_MODEL_REGISTRY: dict[str, ModelRegistration] = {}
_PRE_DELETE_HOOKS: dict[str, PreDeleteHook] = {}
_POST_DELETE_HOOKS: dict[str, PostDeleteHook] = {}
_PRE_RESTORE_HOOKS: dict[str, PreRestoreHook] = {}
_POST_RESTORE_HOOKS: dict[str, PostRestoreHook] = {}


def _default_manager_name(app_label: str, model_name: str) -> str:
    try:
        model_class = apps.get_model(app_label, model_name)
    except LookupError:
        logger.exception("Unable to resolve model %s.%s during file system registration", app_label, model_name)
        return "objects"

    if hasattr(model_class, "objects_including_soft_deleted"):
        return "objects_including_soft_deleted"
    return "objects"


def register_file_system_type(
    type_string: str,
    app_label: str,
    model_name: str,
    *,
    lookup_field: str = "id",
    manager_name: str | None = None,
    team_field: str = "team",
    queryset_modifier: Callable[[Any], Any] | None = None,
    soft_delete_field: str | None = None,
    hard_delete: bool | None = None,
    allow_restore: bool | None = None,
    undo_message: str = "",
) -> None:
    """Register a model that participates in the file system."""

    resolved_manager = manager_name or _default_manager_name(app_label, model_name)
    _MODEL_REGISTRY[type_string] = ModelRegistration(
        app_label=app_label,
        model_name=model_name,
        lookup_field=lookup_field,
        manager_name=resolved_manager,
        team_field=team_field,
        queryset_modifier=queryset_modifier,
        soft_delete_field=soft_delete_field,
        hard_delete=hard_delete,
        allow_restore=allow_restore,
        undo_message=undo_message,
    )


def register_pre_delete_hook(type_string: str, hook: PreDeleteHook) -> None:
    _PRE_DELETE_HOOKS[type_string] = hook


def register_post_delete_hook(type_string: str, hook: PostDeleteHook) -> None:
    _POST_DELETE_HOOKS[type_string] = hook


def register_pre_restore_hook(type_string: str, hook: PreRestoreHook) -> None:
    _PRE_RESTORE_HOOKS[type_string] = hook


def register_post_restore_hook(type_string: str, hook: PostRestoreHook) -> None:
    _POST_RESTORE_HOOKS[type_string] = hook


def is_file_system_type_registered(type_string: str) -> bool:
    return type_string in _MODEL_REGISTRY


def _resolve_user(user: Any | None) -> Any | None:
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    return None


def _get_queryset(registration: ModelRegistration):
    model_class = apps.get_model(registration.app_label, registration.model_name)
    manager = getattr(model_class, registration.manager_name, model_class.objects)
    queryset = manager.all()
    if registration.queryset_modifier:
        queryset = registration.queryset_modifier(queryset)
    return queryset


def _get_object(
    registration: ModelRegistration,
    *,
    ref: str,
    team_id: int | None,
) -> Any:
    queryset = _get_queryset(registration)
    filters: dict[str, Any] = {registration.lookup_field: ref, f"{registration.team_field}_id": team_id}
    return queryset.get(**filters)


def _detect_soft_delete_field(model_class: type[Any], preferred: str | None) -> str | None:
    if preferred:
        return preferred

    for candidate in ("deleted", "is_deleted"):
        field = next((f for f in model_class._meta.fields if f.name == candidate), None)
        if field is None:
            continue
        internal_type = getattr(field, "get_internal_type", lambda: None)()
        if internal_type == "BooleanField":
            return candidate
    return None


def _introspect_model_capabilities(registration: ModelRegistration) -> ModelCapabilities:
    model_class = apps.get_model(registration.app_label, registration.model_name)

    soft_delete_field = None
    if registration.hard_delete is not True:
        soft_delete_field = _detect_soft_delete_field(model_class, registration.soft_delete_field)

    has_soft_delete = soft_delete_field is not None and registration.hard_delete is not True

    if registration.hard_delete is False and soft_delete_field is None:
        raise ValueError(f"Soft delete forced for '{registration.model_name}' but no soft delete field was found.")

    allow_restore = registration.allow_restore
    if allow_restore is None:
        allow_restore = has_soft_delete
    else:
        allow_restore = allow_restore and has_soft_delete

    has_last_modified_by = hasattr(model_class, "last_modified_by")

    return ModelCapabilities(
        soft_delete_field=soft_delete_field if has_soft_delete else None,
        has_last_modified_by=has_last_modified_by,
        can_restore=allow_restore,
    )


def _build_deletion_context(
    entry: FileSystem,
    *,
    user: Any | None,
    request: Any | None,
    team: Any | None,
    organization: Any | None,
) -> DeletionContext:
    resolved_user = _resolve_user(user)
    resolved_team = team or getattr(entry, "team", None)
    return DeletionContext(
        entry=entry,
        user=resolved_user,
        request=request,
        team=resolved_team,
        organization=organization,
    )


def _build_restore_context(
    type_string: str,
    ref: str,
    restore_path: str | None,
    *,
    user: Any | None,
    request: Any | None,
    team: Any | None,
    organization: Any | None,
) -> RestoreContext:
    return RestoreContext(
        type=type_string,
        ref=ref,
        restore_path=restore_path,
        user=_resolve_user(user),
        request=request,
        team=team,
        organization=organization,
    )


def delete_file_system_object(
    entry: FileSystem,
    *,
    user: Any | None = None,
    request: Any | None = None,
    team: Any | None = None,
    organization: Any | None = None,
) -> DeletionResult:
    type_string = entry.type
    ref = entry.ref

    if not ref or type_string == "folder":
        entry.delete()
        return DeletionResult(type=type_string, ref=ref, mode="hard", can_undo=False, undo="")

    registration = _MODEL_REGISTRY.get(type_string)
    if registration is None:
        logger.warning("No model registered for type '%s'. Removing file system entry only.", type_string)
        entry.delete()
        return DeletionResult(type=type_string, ref=ref, mode="hard", can_undo=False, undo="")

    capabilities = _introspect_model_capabilities(registration)
    context = _build_deletion_context(entry, user=user, request=request, team=team, organization=organization)

    try:
        instance = _get_object(registration, ref=ref, team_id=entry.team_id)
    except ObjectDoesNotExist:
        logger.warning("File system entry for type '%s' with ref '%s' has no backing object.", type_string, ref)
        entry.delete()
        return DeletionResult(
            type=type_string,
            ref=ref,
            mode="hard",
            can_undo=False,
            undo=registration.undo_message,
        )

    pre_hook = _PRE_DELETE_HOOKS.get(type_string)
    if pre_hook:
        pre_hook(context, instance)

    if capabilities.has_soft_delete:
        assert capabilities.soft_delete_field is not None
        setattr(instance, capabilities.soft_delete_field, True)
        if capabilities.has_last_modified_by and context.user is not None:
            instance.last_modified_by = context.user
        with mute_selected_signals():
            instance.save()
        entry.delete()
        post_hook = _POST_DELETE_HOOKS.get(type_string)
        if post_hook:
            post_hook(context, instance)
        return DeletionResult(
            type=type_string,
            ref=ref,
            mode="soft",
            can_undo=capabilities.can_restore,
            undo=registration.undo_message,
        )

    if capabilities.has_last_modified_by and context.user is not None:
        instance.last_modified_by = context.user
        with mute_selected_signals():
            instance.save(update_fields=["last_modified_by"])
    with mute_selected_signals():
        instance.delete()
    entry.delete()
    post_hook = _POST_DELETE_HOOKS.get(type_string)
    if post_hook:
        post_hook(context, instance)
    return DeletionResult(
        type=type_string,
        ref=ref,
        mode="hard",
        can_undo=False,
        undo=registration.undo_message,
    )


def undo_delete(
    *,
    type_string: str,
    ref: str,
    restore_path: str | None = None,
    user: Any | None = None,
    request: Any | None = None,
    team: Any | None = None,
    organization: Any | None = None,
) -> Any:
    registration = _MODEL_REGISTRY.get(type_string)
    if registration is None:
        raise ValueError(f"No model registered for type '{type_string}'")

    capabilities = _introspect_model_capabilities(registration)
    if not capabilities.has_soft_delete:
        raise ValueError(f"Type '{type_string}' does not support undo operations")
    if not capabilities.can_restore:
        raise ValueError(f"Undo for type '{type_string}' has been disabled")

    context = _build_restore_context(
        type_string,
        ref,
        restore_path,
        user=user,
        request=request,
        team=team,
        organization=organization,
    )

    team_id = getattr(team, "id", None)
    try:
        instance = _get_object(registration, ref=ref, team_id=team_id)
    except ObjectDoesNotExist as exc:
        raise ValueError(f"Unable to restore {type_string} with ref '{ref}'") from exc

    pre_hook = _PRE_RESTORE_HOOKS.get(type_string)
    if pre_hook:
        pre_hook(context, instance)

    assert capabilities.soft_delete_field is not None
    setattr(instance, capabilities.soft_delete_field, False)

    if restore_path and hasattr(instance, "_create_in_folder"):
        segments = split_path(restore_path)
        folder_path = join_path(segments[:-1]) if len(segments) > 1 else ""
        instance._create_in_folder = folder_path or None

    if capabilities.has_last_modified_by and context.user is not None:
        instance.last_modified_by = context.user

    with mute_selected_signals():
        instance.save()

    post_hook = _POST_RESTORE_HOOKS.get(type_string)
    if post_hook:
        post_hook(context, instance)

    return instance
