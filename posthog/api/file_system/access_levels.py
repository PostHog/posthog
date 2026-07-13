from collections.abc import Sequence
from typing import Any, Optional, cast

from django.apps import apps
from django.db.models import BigIntegerField, CharField, F, QuerySet, Value
from django.db.models.functions import Cast

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.api.file_system.deletion import ModelRegistration, get_file_system_registration
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


def _ref_translation_queryset(
    entry_type: str, registration: ModelRegistration, refs: list[str], project_id: int
) -> QuerySet:
    """Queryset yielding (type, ref, pk, created_by_id) rows for one entry type, with uniform
    column types so querysets of different models can be UNIONed into one statement."""
    model = apps.get_model(registration.app_label, registration.model_name)
    manager = getattr(model, registration.manager_name, model._default_manager)
    lookup_field = registration.lookup_field
    return (
        manager.filter(
            **{
                f"{registration.team_field}__project_id": project_id,
                f"{lookup_field}__in": refs,
            }
        )
        .annotate(
            _type=Value(entry_type, output_field=CharField()),
            _ref=Cast(lookup_field, output_field=CharField()),
            _pk=Cast("pk", output_field=CharField()),
            # Cast rather than Value(None, ...): an untyped NULL lets Postgres resolve the
            # union column as text and clash with real integer columns (see search.py)
            _created_by_id=F("created_by_id")
            if hasattr(model, "created_by")
            else Cast(Value(None), output_field=BigIntegerField()),
        )
        .values_list("_type", "_ref", "_pk", "_created_by_id")
    )


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
    are translated through the registered models - all types UNIONed into a single query.

    Refs that don't resolve to an object still go through resource-level resolution rather
    than short-circuiting to None: refs can be caller-supplied (shortcuts), and a distinct
    value for "doesn't exist" would let members probe guessed refs to learn whether a
    protected object exists.
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

    # One UNION query across every type needing a ref->pk translation or a creator lookup
    translation_querysets = []
    for entry_type, creator_by_provided_ref in entries_by_type.items():
        registration = get_file_system_registration(entry_type)
        if not registration:
            continue
        needs_creator = any(created_by_id is None for created_by_id in creator_by_provided_ref.values())
        if registration.lookup_field == "id" and not needs_creator:
            continue
        translation_querysets.append(
            _ref_translation_queryset(entry_type, registration, list(creator_by_provided_ref), project_id)
        )

    # (type, ref) -> (pk, created_by_id)
    translated: dict[tuple[str, str], tuple[str, Optional[int]]] = {}
    if translation_querysets:
        union_qs = translation_querysets[0]
        if len(translation_querysets) > 1:
            union_qs = union_qs.union(*translation_querysets[1:], all=True)
        for row_type, ref_value, pk_value, created_by_id in union_qs:
            translated[(row_type, str(ref_value))] = (str(pk_value), created_by_id)

    for entry_type, creator_by_provided_ref in entries_by_type.items():
        resource = cast(APIScopeObject, entry_type)

        objects: list[tuple[str, Optional[int]]] = []
        ref_by_pk: dict[str, str] = {}
        for ref, provided_creator in creator_by_provided_ref.items():
            row = translated.get((entry_type, ref))
            # Unresolved refs keep the ref as a pk stand-in: it matches no AccessControl rows,
            # so they resolve at resource level exactly like an existing object without object
            # rows, making guessed refs indistinguishable from real-but-ungranted ones
            pk = row[0] if row else ref
            ref_by_pk[pk] = ref
            objects.append((pk, provided_creator if provided_creator is not None else (row[1] if row else None)))

        # Resolves from the in-memory access control preload - no queries per type
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
