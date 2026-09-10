import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Optional, cast

from django.apps import apps
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import BigIntegerField, CharField, F, QuerySet, Value
from django.db.models.functions import Cast

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.api.file_system.deletion import (
    ModelRegistration,
    get_file_system_registration,
    get_non_pk_keyed_file_system_types,
    is_pk_keyed_file_system_type,
)
from posthog.models import Team
from posthog.scopes import APIScopeObject
from posthog.settings import EE_AVAILABLE

from products.access_control.backend.facade.user_access_control import (
    ACCESS_CONTROL_RESOURCES,
    RESOURCE_INHERITANCE_MAP,
    AccessControlLevel,
    UserAccessControl,
    access_level_satisfied_for_resource,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class FileSystemAccessEntry:
    """One entry to resolve an access level for.

    Keyword-only because `created_by_id` and `team_id` are both ints: positionally they can be
    transposed without any type error, and getting that wrong resolves the entry against the
    wrong team.

    `created_by_id` is the creator of the backing object, never of the tree row that points at
    it, and is None when the caller doesn't know it (it is then read during ref translation).
    `team_id` is the tree row's own team, which is not necessarily the request's team.
    """

    entry_type: str
    ref: Optional[str]
    created_by_id: Optional[int]
    team_id: int


# A ref (short_id) maps to exactly one immutable pk for the life of the object, so the
# translation is safe to cache across requests. Caching it keeps the multi-model UNION off
# the high-traffic list endpoint on every page load - the query that translates short_id refs
# to pks otherwise runs per request and adds DB pool load under contention.
#
# Keyed by project rather than by team, because a team segment would only repeat the project
# one. `TeamManager.create` gives a team the id of its project, creating the project with that
# id when the caller doesn't supply one, and `Project.objects.create_with_team` allocates a
# single id for the pair. No code path attaches a team to an existing project, so a project
# never holds two teams whose refs could collide under one key.
_REF_PK_CACHE_PREFIX = "fs_ref_pk:v1"
_REF_PK_CACHE_TTL = 60 * 60


def _ref_pk_cache_key(project_id: int, entry_type: str, ref: str) -> str:
    return f"{_REF_PK_CACHE_PREFIX}:{project_id}:{entry_type}:{ref}"


def _get_cached_ref_pks(project_id: int, entry_type: str, refs: list[str]) -> dict[str, str]:
    """Return the subset of refs whose pk is already cached. Cache failures degrade to a miss."""
    key_to_ref = {_ref_pk_cache_key(project_id, entry_type, ref): ref for ref in refs}
    try:
        cached = cache.get_many(list(key_to_ref))
    except Exception:
        logger.warning("Failed reading file system ref->pk cache", exc_info=True)
        return {}
    return {key_to_ref[key]: str(pk) for key, pk in cached.items()}


def _set_cached_ref_pks(project_id: int, pk_by_type_ref: dict[tuple[str, str], str]) -> None:
    if not pk_by_type_ref:
        return
    to_set = {_ref_pk_cache_key(project_id, entry_type, ref): pk for (entry_type, ref), pk in pk_by_type_ref.items()}
    try:
        cache.set_many(to_set, timeout=_REF_PK_CACHE_TTL)
    except Exception:
        logger.warning("Failed writing file system ref->pk cache", exc_info=True)


def _is_access_controlled_type(file_system_type: str) -> bool:
    """File system types double as AccessControl resource names; only these types can resolve
    to an access level at all (folders, SQL views, hog functions etc. have no access controls)."""
    return file_system_type in ACCESS_CONTROL_RESOURCES or file_system_type in RESOURCE_INHERITANCE_MAP


def _coerce_refs_for_lookup(model: Any, lookup_field: str, refs: list[str]) -> list[Any]:
    """Refs the lookup field can actually hold, dropping the ones it rejects.

    `ref` is a plain CharField on the tree row and is caller-supplied when a row is created, so
    it can hold a value the target field can't. Passing one into the query raises rather than
    matching nothing: an integer pk raises ValueError on "oops", a UUID pk raises ValidationError.
    Dropped refs then resolve at resource level like any other ref with no matching object, which
    is the same fail-safe unresolvable refs already get.
    """
    field = model._meta.get_field(lookup_field)
    coerced: list[Any] = []
    for ref in refs:
        try:
            coerced.append(field.to_python(ref))
        except (DjangoValidationError, ValueError, TypeError):
            continue
    return coerced


def _ref_translation_queryset(
    entry_type: str, registration: ModelRegistration, refs: list[str], project_id: int
) -> QuerySet:
    """Queryset yielding (type, ref, pk, team_id, created_by_id) rows for one entry type, with
    uniform column types so querysets of different models can be UNIONed into one statement.

    Stays project-wide rather than filtering to one team: short_id uniqueness is enforced per
    team, not per project, so the same ref can legitimately resolve to a different real object
    in every team - the caller keys results by the returned team_id so those don't collide.
    """
    model = apps.get_model(registration.app_label, registration.model_name)
    manager = getattr(model, registration.manager_name, model._default_manager)
    lookup_field = registration.lookup_field
    return (
        manager.filter(
            **{
                f"{registration.team_field}__project_id": project_id,
                f"{lookup_field}__in": _coerce_refs_for_lookup(model, lookup_field, refs),
            }
        )
        .annotate(
            _type=Value(entry_type, output_field=CharField()),
            _ref=Cast(lookup_field, output_field=CharField()),
            _pk=Cast("pk", output_field=CharField()),
            _team_id=F(f"{registration.team_field}_id"),
            # Cast rather than Value(None, ...): an untyped NULL lets Postgres resolve the
            # union column as text and clash with real integer columns (see search.py)
            _created_by_id=F("created_by_id")
            if hasattr(model, "created_by")
            else Cast(Value(None), output_field=BigIntegerField()),
        )
        .values_list("_type", "_ref", "_pk", "_team_id", "_created_by_id")
    )


def _user_access_controls_by_team(
    user_access_control: UserAccessControl, team_ids: Iterable[int]
) -> dict[int, UserAccessControl]:
    """A UserAccessControl scoped to each of the given teams.

    The file system tree intentionally lists rows from every environment in the project (see
    `_scope_by_project_and_environment`), so resolving access has to run against each row's own
    team - a `UserAccessControl` only ever answers for the single team it was built with, and
    silently falls back to `default_access_level` (typically "editor") for objects outside it.
    The caller's own instance serves its own team, and the rest are memoized on it, so the
    filter pass and the serializer pass of one request share them.
    """
    return user_access_control.for_team_ids(team_ids)


def bulk_file_system_access_levels(
    entries: Sequence[FileSystemAccessEntry],
    user_access_control: UserAccessControl,
    project_id: int,
) -> dict[tuple[str, str, int], Optional[AccessControlLevel]]:
    """Resolve the user's access level for the objects behind file system entries, in bulk.

    Pass created_by_id=None when the caller doesn't know the underlying object's creator
    (e.g. shortcuts) - it is then fetched alongside the ref->pk translation. Types without
    access controls resolve to None.

    AccessControl rows are keyed by the target object's pk, while some file system types
    (insight, notebook, session_recording_playlist) use short_id as their ref, so those refs
    are translated through the registered models - the types still needing a DB lookup are
    UNIONed into a single query. The short_id->pk translation is immutable, so it is cached
    across requests, keeping that query off the list endpoint's hot path on a warm cache.

    Refs that don't resolve to an object still go through resource-level resolution rather
    than short-circuiting to None: refs can be caller-supplied (shortcuts), and a distinct
    value for "doesn't exist" would let members probe guessed refs to learn whether a
    protected object exists.

    Final resolution runs per entry's own team_id (see `_user_access_controls_by_team`), and
    results are keyed by (type, ref, team_id), not just (type, ref): `ref` is caller-supplied
    when a tree row is created, so nothing stops the same (type, ref) pair from appearing under
    two different teams in one batch - e.g. a row planted in the caller's own team pointing at
    another team's object. Collapsing those into one (type, ref) entry would let whichever
    team's level was resolved last silently override the other's.

    Translated rows are keyed the same way, by the team the matched object actually belongs to,
    rather than by whichever group triggered the lookup. The pk cache above is keyed by project
    instead, which is the same thing while a project and its team share an id.
    """
    results: dict[tuple[str, str, int], Optional[AccessControlLevel]] = {}
    user_id = user_access_control.user.id

    entries_by_type_team: dict[tuple[str, int], dict[str, Optional[int]]] = {}
    for entry in entries:
        if not entry.ref or not _is_access_controlled_type(entry.entry_type):
            continue
        # The same object can back several entries (e.g. an unfiled row and a user-created one)
        # with different `created_by` values - the row marking the user as creator wins
        by_ref = entries_by_type_team.setdefault((entry.entry_type, entry.team_id), {})
        if by_ref.get(entry.ref) is None or entry.created_by_id == user_id:
            by_ref[entry.ref] = entry.created_by_id

    # (type, ref, team_id) -> (pk, created_by_id)
    translated: dict[tuple[str, str, int], tuple[str, Optional[int]]] = {}

    # Refs still needing a DB lookup, merged across every team's group into one set per type -
    # so a ref two teams' objects happen to share (see the docstring above) is queried once, not
    # once per team. The query itself stays project-wide; every matching row, whichever team it
    # actually belongs to, is captured below and keyed by its own team_id, not by whichever
    # team's group triggered the lookup.
    refs_needing_query_by_type: dict[str, set[str]] = {}
    registrations_by_type: dict[str, ModelRegistration] = {}
    cacheable_types: set[str] = set()  # types safe to backfill the pk cache
    for (entry_type, team_id), creator_by_provided_ref in entries_by_type_team.items():
        registration = get_file_system_registration(entry_type)
        if not registration:
            continue
        registrations_by_type[entry_type] = registration
        needs_creator = any(created_by_id is None for created_by_id in creator_by_provided_ref.values())
        pk_keyed = is_pk_keyed_file_system_type(registration)
        if pk_keyed and not needs_creator:
            continue

        refs = list(creator_by_provided_ref)
        # When we only need the ref->pk translation (not a fresh creator lookup), serve it from
        # the cache and only query the refs still missing - a warm cache takes the UNION off the
        # request entirely. Creator lookups always hit the DB so they never read stale creators.
        if not pk_keyed and not needs_creator:
            cached_pks = _get_cached_ref_pks(project_id, entry_type, refs)
            for ref, pk in cached_pks.items():
                translated[(entry_type, ref, team_id)] = (pk, None)
            refs = [ref for ref in refs if ref not in cached_pks]
            if not refs:
                continue
        if not pk_keyed:
            cacheable_types.add(entry_type)
        refs_needing_query_by_type.setdefault(entry_type, set()).update(refs)

    translation_querysets = [
        _ref_translation_queryset(entry_type, registrations_by_type[entry_type], list(refs), project_id)
        for entry_type, refs in refs_needing_query_by_type.items()
    ]

    if translation_querysets:
        union_qs = translation_querysets[0]
        if len(translation_querysets) > 1:
            union_qs = union_qs.union(*translation_querysets[1:], all=True)
        pk_cache_updates: dict[tuple[str, str], str] = {}
        for row_type, ref_value, pk_value, row_team_id, created_by_id in union_qs:
            ref_str, pk_str = str(ref_value), str(pk_value)
            translated[(row_type, ref_str, row_team_id)] = (pk_str, created_by_id)
            if row_type in cacheable_types:
                pk_cache_updates[(row_type, ref_str)] = pk_str
        _set_cached_ref_pks(project_id, pk_cache_updates)

    access_controls_by_team = _user_access_controls_by_team(
        user_access_control, {team_id for _entry_type, team_id in entries_by_type_team}
    )

    for (entry_type, team_id), creator_by_provided_ref in entries_by_type_team.items():
        resource = cast(APIScopeObject, entry_type)

        if not access_controls_by_team[team_id].has_project_access:
            # Denied the whole environment, so nothing in it resolves. Without this the object
            # rules below fall back to the resource default (editor for most types) for an
            # environment that has no rules of its own, granting exactly what was denied.
            for ref in creator_by_provided_ref:
                results[(entry_type, ref, team_id)] = None
            continue

        objects: list[tuple[str, Optional[int]]] = []
        ref_by_pk: dict[str, str] = {}
        for ref, provided_creator in creator_by_provided_ref.items():
            row = translated.get((entry_type, ref, team_id))
            # Unresolved refs keep the ref as a pk stand-in: it matches no AccessControl rows,
            # so they resolve at resource level exactly like an existing object without object
            # rows, making guessed refs indistinguishable from real-but-ungranted ones
            pk = row[0] if row else ref
            ref_by_pk[pk] = ref
            objects.append((pk, provided_creator if provided_creator is not None else (row[1] if row else None)))

        # Resolved against the entry's own team - resolves from that team's in-memory access
        # control preload, no extra query beyond the one bulk fetch per distinct team
        levels = access_controls_by_team[team_id].bulk_object_access_levels(resource, objects)
        for pk, level in levels.items():
            results[(entry_type, ref_by_pk[pk], team_id)] = level

    return results


def entries_missing_access_level(
    entries: Sequence[tuple[str, str, int]],
    user_access_control: UserAccessControl,
    project_id: int,
    required_level: AccessControlLevel,
) -> list[tuple[str, str]]:
    """The (type, ref) pairs whose backing object the user can't act on at `required_level`.

    `entries` is (type, ref, team_id) - team_id is the tree row's own team, since the tree can
    list rows from sibling environments and resolution has to run against the object's real team.

    Types without access controls resolve to no level and are never reported as missing - the
    file system can only enforce what the object's own resource model defines.

    Creator status is always resolved from the backing object rather than from the file system
    row, so a row someone filed against an object they don't own can't confer the owner's access.
    """
    controlled = [
        (entry_type, ref, team_id)
        for entry_type, ref, team_id in entries
        if ref and _is_access_controlled_type(entry_type)
    ]
    if not controlled:
        return []

    levels = bulk_file_system_access_levels(
        [
            FileSystemAccessEntry(entry_type=entry_type, ref=ref, created_by_id=None, team_id=team_id)
            for entry_type, ref, team_id in controlled
        ],
        user_access_control,
        project_id,
    )
    return [
        (entry_type, ref)
        for entry_type, ref, team_id in controlled
        if (level := levels.get((entry_type, ref, team_id))) is None
        or not access_level_satisfied_for_resource(cast(APIScopeObject, entry_type), level, required_level)
    ]


def denied_short_id_refs(user_access_control: UserAccessControl, project_id: int) -> dict[tuple[str, int], list[str]]:
    """Refs denied by a 'none' grant, for the file system types not keyed by primary key.

    AccessControl rows always store the object's pk in `resource_id`, so for types whose file
    system `ref` is a short_id the grant has to be translated into refs before it can be matched
    against the tree. The tree lists rows from every environment in the project, so a grant has
    to be checked - and its matching ref translated - against the team it was actually made in:
    keyed by (type, team_id) so the caller can exclude a denied ref only within its own team,
    not project-wide.

    Costs one `Team` query per request plus one access-control preload per environment; the
    per-team instances are memoized on `user_access_control`, so the serializer's own resolution
    pass later in the same request reuses them rather than repeating either.
    """
    # Mirrors the early returns in `filter_and_annotate_file_system_queryset`, which discards
    # this result in exactly these cases: these users see everything, and without the
    # entitlement stale rules in the DB must be ignored rather than enforced.
    if user_access_control.user.is_staff or user_access_control.is_organization_admin:
        return {}
    if not EE_AVAILABLE or not user_access_control.access_controls_supported:
        return {}

    resources = [
        entry_type for entry_type in get_non_pk_keyed_file_system_types() if _is_access_controlled_type(entry_type)
    ]
    if not resources:
        return {}

    team_ids = Team.objects.filter(project_id=project_id).values_list("id", flat=True)
    access_controls_by_team = _user_access_controls_by_team(user_access_control, team_ids)

    denied_refs: dict[tuple[str, int], list[str]] = {}
    for team_id, team_uac in access_controls_by_team.items():
        denied_pks = team_uac.none_denied_object_ids(cast(Sequence[APIScopeObject], resources))
        for entry_type, pks in denied_pks.items():
            registration = get_file_system_registration(entry_type)
            if registration is None:
                continue
            model = apps.get_model(registration.app_label, registration.model_name)
            # Grants are stored as strings, so coerce through the model's own pk field rather
            # than assuming a shape - these types include both integer and UUID primary keys,
            # and a value the pk field rejects would make the query raise.
            pk_field = model._meta.pk
            valid_pks = []
            for pk in pks:
                try:
                    valid_pks.append(pk_field.to_python(pk))
                except (DjangoValidationError, ValueError, TypeError):
                    continue
            if not valid_pks:
                continue
            manager = getattr(model, registration.manager_name, model._default_manager)
            refs = manager.filter(**{f"{registration.team_field}_id": team_id, "pk__in": valid_pks}).values_list(
                registration.lookup_field, flat=True
            )
            if refs:
                denied_refs[(entry_type, team_id)] = [str(ref) for ref in refs]
    return denied_refs


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
        self._access_levels_by_type_ref: Optional[dict[tuple[str, str, int], Optional[AccessControlLevel]]] = None

    def _entry_user_access_control(self) -> Optional[UserAccessControl]:
        request = self.context.get("request")
        if request is None or request.user.is_anonymous:
            return None
        view = self.context.get("view")
        return getattr(view, "user_access_control", None)

    def _compute_access_levels(
        self, entries: Sequence[FileSystemAccessEntry], user_access_control: UserAccessControl
    ) -> dict[tuple[str, str, int], Optional[AccessControlLevel]]:
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
                FileSystemAccessEntry(
                    entry_type=instance.type,
                    ref=instance.ref,
                    created_by_id=getattr(instance, "created_by_id", None),
                    team_id=instance.team_id,
                )
                for instance in instances
                if instance is not None and instance.ref
            ]
            self._access_levels_by_type_ref = self._compute_access_levels(entries, user_access_control)

        # Keyed by team_id too: `ref` is caller-supplied, so the same (type, ref) pair could
        # otherwise collapse two different teams' objects onto one resolved level - see
        # bulk_file_system_access_levels.
        key = (obj.type, obj.ref, obj.team_id)
        if key not in self._access_levels_by_type_ref:
            # Object wasn't part of the preloaded batch (e.g. freshly created) - resolve it alone
            self._access_levels_by_type_ref.update(
                self._compute_access_levels(
                    [
                        FileSystemAccessEntry(
                            entry_type=obj.type,
                            ref=obj.ref,
                            created_by_id=getattr(obj, "created_by_id", None),
                            team_id=obj.team_id,
                        )
                    ],
                    user_access_control,
                )
            )
        return self._access_levels_by_type_ref.get(key)
