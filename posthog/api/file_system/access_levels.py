from collections.abc import Sequence
from typing import Any, Optional, cast

from django.apps import apps

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.api.file_system.deletion import get_file_system_registration
from posthog.rbac.user_access_control import (
    ACCESS_CONTROL_RESOURCES,
    RESOURCE_INHERITANCE_MAP,
    AccessControlLevel,
    UserAccessControl,
)
from posthog.scopes import APIScopeObject

# (file system type, ref, created_by_id of the underlying object - None when unknown)
FileSystemAccessEntry = tuple[str, Optional[str], Optional[int]]


def _is_access_controlled_type(file_system_type: str) -> bool:
    """File system types double as AccessControl resource names; only these types can resolve
    to an access level at all (folders, SQL views, hog functions etc. have no access controls)."""
    return file_system_type in ACCESS_CONTROL_RESOURCES or file_system_type in RESOURCE_INHERITANCE_MAP


def bulk_file_system_access_levels(
    entries: Sequence[FileSystemAccessEntry],
    user_access_control: UserAccessControl,
    project_id: int,
) -> dict[tuple[str, str], Optional[AccessControlLevel]]:
    """Resolve the user's access level for the objects behind file system entries, in bulk.

    Pass created_by_id=None when the caller doesn't know the underlying object's creator
    (e.g. shortcuts) - it is then fetched alongside the ref->pk translation. Types without
    access controls resolve to None.

    AccessControl rows are keyed by the target object's pk, while some file system types
    (insight, notebook, session_recording_playlist) use short_id as their ref, so those refs
    are translated through the registered model - at most one query per type present.
    """
    results: dict[tuple[str, str], Optional[AccessControlLevel]] = {}
    user_id = user_access_control.user.id

    entries_by_type: dict[str, dict[str, Optional[int]]] = {}
    for entry_type, ref, created_by_id in entries:
        if not ref or not _is_access_controlled_type(entry_type):
            continue
        by_ref = entries_by_type.setdefault(entry_type, {})
        # The same object can back several entries (e.g. an unfiled row and a user-created one)
        # with different `created_by` values - the row marking the user as creator wins
        if by_ref.get(ref) is None or created_by_id == user_id:
            by_ref[ref] = created_by_id

    for entry_type, creator_by_provided_ref in entries_by_type.items():
        resource = cast(APIScopeObject, entry_type)
        registration = get_file_system_registration(entry_type)
        lookup_field = registration.lookup_field if registration else "id"
        needs_creator = any(created_by_id is None for created_by_id in creator_by_provided_ref.values())

        pk_by_ref: dict[str, str] = {}
        creator_by_ref: dict[str, Optional[int]] = {}
        if registration and (lookup_field != "id" or needs_creator):
            model = apps.get_model(registration.app_label, registration.model_name)
            manager = getattr(model, registration.manager_name, model._default_manager)
            columns = [lookup_field, "pk"] + (["created_by_id"] if hasattr(model, "created_by") else [])
            rows = manager.filter(
                **{
                    f"{registration.team_field}__project_id": project_id,
                    f"{lookup_field}__in": list(creator_by_provided_ref),
                }
            ).values_list(*columns)
            for row in rows:
                ref_value = str(row[0])
                pk_by_ref[ref_value] = str(row[1])
                creator_by_ref[ref_value] = row[2] if len(row) > 2 else None

        objects: list[tuple[str, Optional[int]]] = []
        ref_by_pk: dict[str, str] = {}
        for ref, provided_creator in creator_by_provided_ref.items():
            pk = ref if lookup_field == "id" else pk_by_ref.get(ref)
            if pk is None:
                # The ref no longer resolves to an object - nothing to gate on
                results[(entry_type, ref)] = None
                continue
            ref_by_pk[pk] = ref
            objects.append((pk, provided_creator if provided_creator is not None else creator_by_ref.get(ref)))

        levels = user_access_control.bulk_object_access_levels(resource, objects)
        for pk, level in levels.items():
            results[(entry_type, ref_by_pk[pk])] = level

    return results


# Adds a `user_access_level` field to serializers of models that reference project objects
# via (type, ref) - resolved in bulk, once per serialization. Deliberately no class docstring:
# drf-spectacular inherits it (via inspect.getdoc) as the schema description of every
# serializer that mixes this in.
class FileSystemAccessLevelSerializerMixin(serializers.Serializer):
    user_access_level = serializers.SerializerMethodField(
        read_only=True,
        help_text=(
            "Resolved access level the user has for the object this entry references "
            "('none' means the user can't open it). Null when access controls don't apply "
            "to the entry type."
        ),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._access_levels_by_type_ref: Optional[dict[tuple[str, str], Optional[AccessControlLevel]]] = None

    def _entry_user_access_control(self) -> Optional[UserAccessControl]:
        request = self.context.get("request")
        if request is None or request.user.is_anonymous:
            return None
        view = self.context.get("view")
        return getattr(view, "user_access_control", None)

    def _compute_access_levels(
        self, entries: Sequence[FileSystemAccessEntry], user_access_control: UserAccessControl
    ) -> dict[tuple[str, str], Optional[AccessControlLevel]]:
        team = self.context["get_team"]()
        return bulk_file_system_access_levels(entries, user_access_control, team.project_id)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_user_access_level(self, obj: Any) -> Optional[str]:
        user_access_control = self._entry_user_access_control()
        if user_access_control is None or not obj.ref or not _is_access_controlled_type(obj.type):
            return None

        if self._access_levels_by_type_ref is None:
            instances = self.instance if isinstance(self.instance, list) else [self.instance]
            entries = [
                (instance.type, instance.ref, getattr(instance, "created_by_id", None))
                for instance in instances
                if instance is not None and instance.ref
            ]
            self._access_levels_by_type_ref = self._compute_access_levels(entries, user_access_control)

        key = (obj.type, obj.ref)
        if key not in self._access_levels_by_type_ref:
            # Object wasn't part of the preloaded batch (e.g. freshly created) - resolve it alone
            self._access_levels_by_type_ref.update(
                self._compute_access_levels(
                    [(obj.type, obj.ref, getattr(obj, "created_by_id", None))], user_access_control
                )
            )
        return self._access_levels_by_type_ref.get(key)
