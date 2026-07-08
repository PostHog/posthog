"""Centralized test helpers for person, group, and cohort data creation.

Every test that needs person/group/cohort data should use these helpers rather
than calling ORM methods directly.  personhog is the sole source of truth, so
these helpers seed the active personhog fake (and, for persons, ClickHouse) —
they do NOT write to the persons DB.  Person/group rows are returned as unsaved
Django instances carrying synthetic primary keys so attribute access and
serializers keep working without a database round-trip.

The persons DB router raises on any ORM access to persons-DB models while a
test's personhog fake is active, so a direct `Person.objects.create(...)` in a
test will fail loudly — route through these helpers instead.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from django.utils.timezone import now

from posthog.models import signals
from posthog.models.group.group import Group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.person import Person, PersonDistinctId
from posthog.models.person.util import (
    create_person as _ch_create_person,
    create_person_distinct_id as _ch_create_person_distinct_id,
)
from posthog.models.utils import UUIDT
from posthog.persons_db import persons_db_connection
from posthog.persons_seed import (
    insert_seed_distinct_id,
    insert_seed_group,
    insert_seed_group_type_mapping,
    insert_seed_person,
)

if TYPE_CHECKING:
    import uuid

    from posthog.models.team import Team

    from products.cohorts.backend.models.cohort import Cohort


# ── Internal state for deferred (batched) creation + synthetic ids ────

_persons_cache: list[dict[str, Any]] = []
_persons_ordering_int: int = 0
_next_pk: int = 0


def _next_synthetic_pk() -> int:
    """Synthetic primary key for in-memory person/group rows (reset per test)."""
    global _next_pk
    _next_pk += 1
    return _next_pk


def _next_deterministic_uuid() -> uuid.UUID:
    """Generate a deterministic UUID for consistent test ordering."""
    import uuid as _uuid  # noqa: PLC0415

    global _persons_ordering_int
    result = _uuid.UUID(int=_persons_ordering_int, version=4)
    _persons_ordering_int += 1
    return result


def reset_persons_state() -> None:
    """Reset deferred persons cache, UUID counter, and pk counter.  Called from BaseTest.tearDown."""
    global _persons_ordering_int, _next_pk
    _persons_cache.clear()
    _persons_ordering_int = 0
    _next_pk = 0


def has_unflushed_persons() -> bool:
    return len(_persons_cache) > 0


def clear_persons_cache() -> None:
    _persons_cache.clear()


# ── Fake seeding internals ───────────────────────────────────────────


def _get_active_fake():
    from posthog.personhog_client.fake_client import _active_fake  # noqa: PLC0415

    return _active_fake


def _datetime_to_ms(val: dt.datetime | None) -> int:
    if val is None:
        return 0
    return int(val.timestamp() * 1000)


def _seed_person_into_fake(
    person: Person,
    distinct_ids: list[str],
    *,
    created_at_ms: int | None = None,
    distinct_id_versions: dict[str, int] | None = None,
) -> None:
    """Seed a person + distinct IDs into the active fake.  No-op if no fake is active."""
    fake = _get_active_fake()
    if fake is None:
        return

    existing_dids = {d.distinct_id for d in fake._distinct_ids.get((person.team_id, person.pk), [])}
    new_dids = [str(did) for did in distinct_ids if str(did) not in existing_dids]

    person_proto = fake.add_person(
        team_id=person.team_id,
        person_id=person.pk,
        uuid=str(person.uuid),
        properties=person.properties or {},
        created_at=created_at_ms if created_at_ms is not None else _datetime_to_ms(person.created_at),
        version=person.version or 0,
        is_identified=person.is_identified,
        distinct_ids=new_dids,
        distinct_id_versions=distinct_id_versions or {},
        last_seen_at=_datetime_to_ms(person.last_seen_at),
    )

    for did_with_ver in fake._distinct_ids.get((person.team_id, person.pk), []):
        fake._persons_by_distinct_id[(person.team_id, did_with_ver.distinct_id)] = person_proto


def _reseed_person_into_fake(person: Person) -> None:
    """Re-seed an existing person into the fake after an update (e.g. property change)."""
    fake = _get_active_fake()
    if fake is None:
        return

    person_proto = fake.add_person(
        team_id=person.team_id,
        person_id=person.pk,
        uuid=str(person.uuid),
        properties=person.properties or {},
        created_at=_datetime_to_ms(person.created_at),
        version=person.version or 0,
        is_identified=person.is_identified,
        last_seen_at=_datetime_to_ms(person.last_seen_at),
    )
    for did_with_ver in fake._distinct_ids.get((person.team_id, person.pk), []):
        fake._persons_by_distinct_id[(person.team_id, did_with_ver.distinct_id)] = person_proto


def _seed_distinct_id_into_fake(team_id: int, person_id: int, distinct_id: str, version: int = 0) -> None:
    """Seed a single distinct ID into the fake.  No-op if no fake is active."""
    fake = _get_active_fake()
    if fake is None:
        return

    from posthog.personhog_client.proto.generated.personhog.types.v1 import person_pb2  # noqa: PLC0415

    person_proto = fake._persons_by_id.get((team_id, person_id))
    if person_proto is None:
        return

    existing_dids = {d.distinct_id for d in fake._distinct_ids.get((team_id, person_id), [])}
    if distinct_id in existing_dids:
        return

    fake._persons_by_distinct_id[(team_id, distinct_id)] = person_proto
    fake._distinct_ids.setdefault((team_id, person_id), []).append(
        person_pb2.DistinctIdWithVersion(distinct_id=distinct_id, version=version)
    )


def _seed_group_into_fake(group: Group) -> None:
    fake = _get_active_fake()
    if fake is None:
        return
    fake.add_group(
        team_id=group.team_id,
        group_type_index=group.group_type_index,
        group_key=group.group_key,
        group_properties=group.group_properties or {},
        id=group.pk,
        created_at=_datetime_to_ms(group.created_at),
        version=group.version or 0,
    )


def _seed_group_type_mapping_into_fake(instance: GroupTypeMapping) -> None:
    fake = _get_active_fake()
    if fake is None:
        return

    project_mappings = fake._group_type_mappings_by_project.get(instance.project_id, [])
    fake._group_type_mappings_by_project[instance.project_id] = [
        m for m in project_mappings if m.group_type_index != instance.group_type_index
    ]
    if instance.team_id:
        team_mappings = fake._group_type_mappings_by_team.get(instance.team_id, [])
        fake._group_type_mappings_by_team[instance.team_id] = [
            m
            for m in team_mappings
            if not (m.project_id == instance.project_id and m.group_type_index == instance.group_type_index)
        ]

    fake.add_group_type_mapping(
        project_id=instance.project_id,
        team_id=instance.team_id,
        group_type=instance.group_type,
        group_type_index=instance.group_type_index,
        id=instance.pk,
        name_singular=instance.name_singular or "",
        name_plural=instance.name_plural or "",
        detail_dashboard_id=instance.detail_dashboard_id or 0,
        default_columns=list(instance.default_columns) if instance.default_columns else None,
        created_at=_datetime_to_ms(instance.created_at),
    )


def _seed_cohort_member_into_fake(cohort_id: int, person_id: int) -> None:
    fake = _get_active_fake()
    if fake is None:
        return
    if (cohort_id, person_id) not in fake._cohort_members:
        fake.add_cohort_membership(person_id=person_id, cohort_id=cohort_id, is_member=True)


def _remove_cohort_member_from_fake(cohort_id: int, person_id: int) -> None:
    fake = _get_active_fake()
    if fake is None:
        return
    fake._cohort_members.pop((cohort_id, person_id), None)
    memberships = fake._cohort_memberships.get(person_id)
    if memberships is not None:
        fake._cohort_memberships[person_id] = [m for m in memberships if m.cohort_id != cohort_id]


# ── ClickHouse sync (replaces the post_save/post_delete signal mirror) ─


def _ch_sync_person(person: Person, distinct_ids: list[str]) -> None:
    """Mirror a person + its distinct ids into ClickHouse, matching the old
    post_save signal behavior that fired on ORM creation.  Like that signal it is
    a @mutable_receiver, so mute_selected_signals() suppresses the ClickHouse write."""
    if signals.is_muted:
        return
    _ch_create_person(
        team_id=person.team_id,
        properties=person.properties or {},
        uuid=str(person.uuid),
        is_identified=person.is_identified,
        version=person.version or 0,
        created_at=person.created_at,
    )
    for distinct_id in distinct_ids:
        _ch_create_person_distinct_id(person.team_id, str(distinct_id), str(person.uuid), version=0)


# ── Person instance construction (unsaved, synthetic pk) ──────────────


def _build_person(create_kwargs: dict[str, Any]) -> Person:
    if not create_kwargs.get("uuid"):
        create_kwargs["uuid"] = UUIDT()
    person = Person(**create_kwargs)
    person.id = _next_synthetic_pk()
    person.created_at = person.created_at or now()
    person.version = person.version or 0
    person._state.adding = False
    return person


# ── Public helpers: Person ───────────────────────────────────────────


def create_people_bulk(specs: list[dict[str, Any]]) -> list[Person]:
    """Create many persons at once: one ClickHouse insert per table instead of two per person.

    Each spec is a create_person() kwargs dict (team/team_id, distinct_ids, uuid, ...). Row values
    mirror what create_person writes via posthog.models.person.util.create_person /
    create_person_distinct_id, so the stored ClickHouse data is identical — only batched. The
    persons-DB-layer path (fake off) falls back to per-person create_person.
    """
    import json  # noqa: PLC0415

    from posthog.clickhouse.client import sync_execute  # noqa: PLC0415
    from posthog.models.person.sql import BULK_INSERT_PERSON_DISTINCT_ID2, INSERT_PERSON_BULK_SQL  # noqa: PLC0415

    if _get_active_fake() is None:
        return [create_person(**spec) for spec in specs]

    persons: list[Person] = []
    person_rows: list[dict[str, Any]] = []
    distinct_id_rows: list[dict[str, Any]] = []
    for spec in specs:
        create_kwargs = {key: value for key, value in spec.items() if key != "distinct_ids"}
        if "team" in create_kwargs and create_kwargs["team"] is None:
            create_kwargs.pop("team")
        dids = [str(d) for d in (spec.get("distinct_ids") or [])]
        person = _build_person(create_kwargs)
        person._distinct_ids = list(dids)
        if not signals.is_muted:
            timestamp = now().astimezone(dt.UTC).replace(tzinfo=None)
            created_at = person.created_at.astimezone(dt.UTC).replace(tzinfo=None) if person.created_at else timestamp
            person_rows.append(
                {
                    "id": str(person.uuid),
                    "created_at": created_at,
                    "team_id": person.team_id,
                    "properties": json.dumps(person.properties or {}),
                    "is_identified": int(person.is_identified),
                    "_timestamp": timestamp,
                    "_offset": 0,
                    "is_deleted": 0,
                    "version": person.version or 0,
                    "last_seen_at": timestamp.replace(minute=0, second=0, microsecond=0),
                }
            )
            for distinct_id in dids:
                distinct_id_rows.append(
                    {
                        "distinct_id": distinct_id,
                        "person_id": str(person.uuid),
                        "team_id": person.team_id,
                        "is_deleted": 0,
                        "version": 0,
                        "_timestamp": timestamp,
                        "_offset": 0,
                        "_partition": 0,
                    }
                )
        _seed_person_into_fake(person, dids)
        persons.append(person)

    if person_rows:
        sync_execute(INSERT_PERSON_BULK_SQL, person_rows, flush=False)
    if distinct_id_rows:
        sync_execute(BULK_INSERT_PERSON_DISTINCT_ID2, distinct_id_rows, flush=False)
    return persons


def create_person(*, team: Team | None = None, distinct_ids: list[str] | None = None, **kwargs: Any) -> Person:
    """Create a person for tests.

    Consumer tests (the personhog fake is active): seed ClickHouse + the fake,
    no persons DB write.  Persons-DB-layer tests (the fake is off / excluded in
    conftest): write real persons-DB rows so the code under test, which reads the
    persons DB directly, sees them — matching the pre-personhog behavior.
    """
    if team is None and "team_id" not in kwargs:
        raise TypeError("create_person() requires 'team' or 'team_id'")
    create_kwargs: dict[str, Any] = {**kwargs}
    if team is not None:
        create_kwargs["team"] = team

    dids = [str(d) for d in (distinct_ids or [])]

    if _get_active_fake() is None:
        return _create_person_in_persons_db(create_kwargs, dids)

    person = _build_person(create_kwargs)
    person._distinct_ids = list(dids)
    _ch_sync_person(person, dids)
    _seed_person_into_fake(person, dids)
    return person


def _create_person_in_persons_db(create_kwargs: dict[str, Any], dids: list[str]) -> Person:
    """Write a real persons-DB person + distinct ids via off-Django psycopg (fake-off / excluded tests).

    Builds the Person instance to resolve the same field defaults Person.objects.create would
    (uuid, created_at, version), then inserts directly so this path needs no Django persons connection.
    """
    person = Person(**create_kwargs)
    if not person.uuid:
        person.uuid = UUIDT()
    person.created_at = person.created_at or now()

    with persons_db_connection(writer=True, autocommit=True) as conn:
        person.id = insert_seed_person(
            conn,
            team_id=person.team_id,
            properties=person.properties or {},
            is_identified=person.is_identified,
            uuid=person.uuid,
            version=person.version,
            created_at=person.created_at,
            last_seen_at=person.last_seen_at,
            properties_last_updated_at=person.properties_last_updated_at,
            properties_last_operation=person.properties_last_operation,
        )
        for distinct_id in dids:
            insert_seed_distinct_id(conn, team_id=person.team_id, person_id=person.id, distinct_id=distinct_id)

    person._state.adding = False
    person._distinct_ids = list(dids)
    _ch_sync_person(person, dids)
    return person


def delete_person(person: Person) -> None:
    """Soft-delete a person in ClickHouse and unseed the personhog fake.

    Mirrors posthog.models.person.util.delete_person: writes CH tombstones with
    version + 100 (so the delete wins over normal updates) for the person and each
    of its distinct IDs, then removes it from the fake.
    """
    fake = _get_active_fake()
    if fake is None:
        return
    from posthog.personhog_client.proto.generated.personhog.types.v1 import person_pb2  # noqa: PLC0415

    dids_with_version = list(fake._distinct_ids.get((person.team_id, person.pk), []))
    _ch_create_person(
        team_id=person.team_id,
        properties=person.properties or {},
        uuid=str(person.uuid),
        is_identified=person.is_identified,
        version=(person.version or 0) + 100,
        created_at=person.created_at,
        is_deleted=True,
    )
    for did in dids_with_version:
        _ch_create_person_distinct_id(
            person.team_id, did.distinct_id, str(person.uuid), version=(did.version or 0) + 100, is_deleted=True
        )

    fake.delete_persons(person_pb2.DeletePersonsRequest(team_id=person.team_id, person_uuids=[str(person.uuid)]))


def update_person(person: Person) -> None:
    """Re-sync a mutated person into ClickHouse and the personhog fake."""
    _ch_create_person(
        team_id=person.team_id,
        properties=person.properties or {},
        uuid=str(person.uuid),
        is_identified=person.is_identified,
        version=person.version or 0,
        created_at=person.created_at,
    )
    _reseed_person_into_fake(person)


def add_distinct_id(*, person: Person, distinct_id: str, version: int = 0) -> PersonDistinctId:
    """Add a distinct ID to a person in ClickHouse + the personhog fake (or the persons DB when fake-off)."""
    if not signals.is_muted:
        _ch_create_person_distinct_id(person.team_id, str(distinct_id), str(person.uuid), version=version)

    existing_distinct_ids = getattr(person, "_distinct_ids", None)
    if existing_distinct_ids is not None and distinct_id not in existing_distinct_ids:
        existing_distinct_ids.append(distinct_id)

    if _get_active_fake() is None:
        with persons_db_connection(writer=True, autocommit=True) as conn:
            insert_seed_distinct_id(
                conn, team_id=person.team_id, person_id=person.pk, distinct_id=str(distinct_id), version=version
            )
        return PersonDistinctId(team_id=person.team_id, person=person, distinct_id=str(distinct_id), version=version)

    _seed_distinct_id_into_fake(person.team_id, person.pk, distinct_id, version=version)
    return PersonDistinctId(team_id=person.team_id, person=person, distinct_id=distinct_id, version=version)


def stage_person_for_bulk_create(*args: Any, **kwargs: Any) -> Person:
    """Stage a person for deferred bulk creation.

    Does NOT write immediately.  Call flush_persons_and_events() to bulk-insert
    all staged persons into ClickHouse + the personhog fake.

    Returns an unsaved Person instance (no pk).  The pk is only available
    after flush.
    """
    if not kwargs.get("uuid"):
        kwargs["uuid"] = _next_deterministic_uuid()
    else:
        _next_deterministic_uuid()

    if kwargs.get("immediate") or (
        hasattr(dt.datetime.now(), "__module__") and dt.datetime.now().__module__ == "freezegun.api"
    ):
        kwargs.pop("immediate", None)
        return create_person(**kwargs)

    if len(args) > 0:
        kwargs["distinct_ids"] = [args[0]]

    _persons_cache.append(kwargs)
    return Person(**{key: value for key, value in kwargs.items() if key != "distinct_ids"})


def flush_persons_to_db_and_clickhouse() -> dict[str, Person]:
    """Bulk-insert all staged persons into ClickHouse + the personhog fake.

    Returns the person_mapping (distinct_id → Person) for event flushing.
    Called by flush_persons_and_events() in base.py.
    """
    from posthog.models.person.util import bulk_create_persons  # noqa: PLC0415

    if len(_persons_cache) == 0:
        return {}

    person_mapping = bulk_create_persons(_persons_cache)
    _persons_cache.clear()
    _seed_persons_from_bulk_mapping(person_mapping)
    return person_mapping


def _seed_persons_from_bulk_mapping(person_mapping: dict[str, Person]) -> None:
    """Seed the fake from bulk_create_persons output with timestamp spreading."""
    fake = _get_active_fake()
    if fake is None:
        return

    by_person: dict[int, tuple[Person, list[str]]] = {}
    for distinct_id, person in person_mapping.items():
        _, dids = by_person.setdefault(person.pk, (person, []))
        dids.append(str(distinct_id))

    prev_ms = 0
    for pk in sorted(by_person):
        person, dids = by_person[pk]
        created_at_ms = max(_datetime_to_ms(person.created_at), prev_ms + 1)
        prev_ms = created_at_ms
        _seed_person_into_fake(person, dids, created_at_ms=created_at_ms)


# ── Public helpers: Group ────────────────────────────────────────────


def create_group(*, team: Team | None = None, group_type_index: int, group_key: str, **kwargs: Any) -> Group:
    """Create a group for tests.

    Fake active: seed the personhog fake only (no persons DB write).  Fake off
    (excluded layer/seed tests): write a real persons-DB row so code that reads
    the persons DB directly sees it.
    """
    if team is None and "team_id" not in kwargs:
        raise TypeError("create_group() requires 'team' or 'team_id'")
    create_kwargs: dict[str, Any] = {"group_type_index": group_type_index, "group_key": group_key, **kwargs}
    if team is not None:
        create_kwargs["team"] = team

    if _get_active_fake() is None:
        group = Group(**create_kwargs)
        group.created_at = group.created_at or now()
        group.version = group.version or 0
        with persons_db_connection(writer=True, autocommit=True) as conn:
            group.id = insert_seed_group(
                conn,
                team_id=group.team_id,
                group_key=group.group_key,
                group_type_index=group.group_type_index,
                group_properties=group.group_properties or {},
                version=group.version,
                created_at=group.created_at,
            )
        group._state.adding = False
        return group

    group = Group(**create_kwargs)
    group.id = _next_synthetic_pk()
    group.created_at = group.created_at or now()
    group.version = group.version or 0
    group._state.adding = False
    _seed_group_into_fake(group)
    return group


def update_group(group: Group) -> None:
    """Re-seed a mutated group into the personhog fake."""
    _seed_group_into_fake(group)


# ── Public helpers: GroupTypeMapping ─────────────────────────────────


def create_group_type_mapping(*, team: Team | None = None, **kwargs: Any) -> GroupTypeMapping:
    """Create a group type mapping for tests.

    Fake active: seed the personhog fake only (no persons DB write).  Fake off
    (excluded layer tests): write a real persons-DB row so code that reads the
    persons DB directly sees it.
    """
    if team is not None:
        kwargs["team"] = team

    if _get_active_fake() is None:
        mapping = GroupTypeMapping(**kwargs)
        if mapping.created_at is None:
            mapping.created_at = now()
        with persons_db_connection(writer=True, autocommit=True) as conn:
            mapping.id = insert_seed_group_type_mapping(
                conn,
                project_id=mapping.project_id,
                team_id=mapping.team_id,
                group_type=mapping.group_type,
                group_type_index=mapping.group_type_index,
                name_singular=mapping.name_singular,
                name_plural=mapping.name_plural,
                default_columns=list(mapping.default_columns) if mapping.default_columns is not None else None,
                detail_dashboard_id=mapping.detail_dashboard_id,
                created_at=mapping.created_at,
            )
        mapping._state.adding = False
        return mapping

    mapping = GroupTypeMapping(**kwargs)
    mapping.id = _next_synthetic_pk()
    if mapping.created_at is None:
        mapping.created_at = now()
    mapping._state.adding = False
    _seed_group_type_mapping_into_fake(mapping)
    return mapping


def update_group_type_mapping(mapping: GroupTypeMapping) -> None:
    """Re-seed a mutated group type mapping into the personhog fake."""
    _seed_group_type_mapping_into_fake(mapping)


# ── Public helpers: Cohort membership ────────────────────────────────


def add_cohort_members(cohort: Cohort, persons: list[Person]) -> None:
    """Add persons to a cohort in the personhog fake."""
    for person in persons:
        _seed_cohort_member_into_fake(cohort.pk, person.pk)


def remove_cohort_members(cohort: Cohort, persons: list[Person]) -> None:
    """Remove persons from a cohort in the personhog fake."""
    for person in persons:
        _remove_cohort_member_from_fake(cohort.pk, person.pk)
