"""Centralized test helpers for person, group, and cohort data creation.

Every test that needs person/group/cohort data should use these helpers
rather than calling ORM methods directly.  Each helper writes to the ORM
(Postgres) and seeds the active personhog fake so both read paths see the data.

Transitional: when the ORM fallback and persons DB connection are removed,
the ORM writes in these helpers can be deleted — only the fake-seeding remains.
That's the single place to change.
"""

from __future__ import annotations

import uuid
import datetime as dt
from typing import TYPE_CHECKING, Any

from posthog.models.group.group import Group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.person import Person, PersonDistinctId

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.cohorts.backend.models.cohort import Cohort


# ── Internal state for deferred (batched) creation ───────────────────

_persons_cache: list[dict[str, Any]] = []
_persons_ordering_int: int = 0


def _next_deterministic_uuid() -> uuid.UUID:
    """Generate a deterministic UUID for consistent test ordering."""
    global _persons_ordering_int
    result = uuid.UUID(int=_persons_ordering_int, version=4)
    _persons_ordering_int += 1
    return result


def reset_persons_state() -> None:
    """Reset deferred persons cache and UUID counter.  Called from BaseTest.tearDown."""
    global _persons_ordering_int
    _persons_cache.clear()
    _persons_ordering_int = 0


def has_unflushed_persons() -> bool:
    return len(_persons_cache) > 0


def clear_persons_cache() -> None:
    _persons_cache.clear()


# ── Fake seeding internals ───────────────────────────────────────────


def _get_active_fake():
    from posthog.test.personhog_fake import _active_fake  # noqa: PLC0415

    return _active_fake


def _datetime_to_ms(val: dt.datetime | None) -> int:
    if val is None:
        return 0
    return int(val.timestamp() * 1000)


def _seed_person_into_fake(person: Person, distinct_ids: list[str], *, created_at_ms: int | None = None) -> None:
    """Seed a person + distinct IDs into the active fake.  No-op if no fake is active."""
    fake = _get_active_fake()
    if fake is None:
        return

    existing_dids = {d.distinct_id for d in fake._distinct_ids.get((person.team_id, person.pk), [])}
    new_dids = [str(did) for did in distinct_ids if str(did) not in existing_dids]

    distinct_id_versions: dict[str, int] = {}
    if new_dids:
        for pdi in PersonDistinctId.objects.filter(  # nosemgrep: no-direct-persons-db-orm
            team_id=person.team_id, person_id=person.pk, distinct_id__in=new_dids
        ):
            distinct_id_versions[pdi.distinct_id] = pdi.version or 0

    person_proto = fake.add_person(
        team_id=person.team_id,
        person_id=person.pk,
        uuid=str(person.uuid),
        properties=person.properties or {},
        created_at=created_at_ms if created_at_ms is not None else _datetime_to_ms(person.created_at),
        version=person.version or 0,
        is_identified=person.is_identified,
        distinct_ids=new_dids,
        distinct_id_versions=distinct_id_versions,
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


# ── Public helpers: Person ───────────────────────────────────────────


def create_person(*, team: Team | None = None, distinct_ids: list[str] | None = None, **kwargs: Any) -> Person:
    """Create a person immediately in Postgres and seed the personhog fake."""
    if team is None and "team_id" not in kwargs:
        raise TypeError("create_person() requires 'team' or 'team_id'")
    create_kwargs: dict[str, Any] = {**kwargs}
    if team is not None:
        create_kwargs["team"] = team
    if distinct_ids:
        create_kwargs["distinct_ids"] = distinct_ids
    person = Person.objects.create(**create_kwargs)  # nosemgrep: no-direct-persons-db-orm
    _seed_person_into_fake(person, distinct_ids or [])
    return person


def update_person(person: Person) -> None:
    """Save a person to Postgres and re-seed the personhog fake."""
    person.save()  # nosemgrep: no-direct-persons-db-orm
    _reseed_person_into_fake(person)


def add_distinct_id(*, person: Person, distinct_id: str, version: int = 0) -> PersonDistinctId:
    """Create a PersonDistinctId in Postgres and seed it into the personhog fake."""
    pdi = PersonDistinctId.objects.create(  # nosemgrep: no-direct-persons-db-orm
        team_id=person.team_id,
        person=person,
        distinct_id=distinct_id,
        version=version,
    )
    _seed_distinct_id_into_fake(person.team_id, person.pk, distinct_id, version=version)
    return pdi


def stage_person_for_bulk_create(*args: Any, **kwargs: Any) -> Person:
    """Stage a person for deferred bulk creation.

    Does NOT write to Postgres or ClickHouse immediately.  Call
    flush_persons_and_events() to bulk-insert all staged persons into
    Postgres + ClickHouse + personhog fake.

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
    """Bulk-insert all staged persons into Postgres + ClickHouse + personhog fake.

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
    """Create a group in Postgres and seed the personhog fake."""
    if team is None and "team_id" not in kwargs:
        raise TypeError("create_group() requires 'team' or 'team_id'")
    create_kwargs: dict[str, Any] = {"group_type_index": group_type_index, "group_key": group_key, **kwargs}
    if team is not None:
        create_kwargs["team"] = team
    group = Group.objects.create(**create_kwargs)  # nosemgrep: no-direct-persons-db-orm
    _seed_group_into_fake(group)
    return group


def update_group(group: Group) -> None:
    """Save a group to Postgres and re-seed the personhog fake."""
    group.save()  # nosemgrep: no-direct-persons-db-orm
    _seed_group_into_fake(group)


# ── Public helpers: GroupTypeMapping ─────────────────────────────────


def create_group_type_mapping(*, team: Team | None = None, **kwargs: Any) -> GroupTypeMapping:
    """Create a group type mapping in Postgres and seed the personhog fake."""
    if team is not None:
        kwargs["team"] = team
    mapping = GroupTypeMapping.objects.create(**kwargs)  # nosemgrep: no-direct-persons-db-orm
    _seed_group_type_mapping_into_fake(mapping)
    return mapping


def update_group_type_mapping(mapping: GroupTypeMapping) -> None:
    """Save a group type mapping to Postgres and re-seed the personhog fake."""
    mapping.save()  # nosemgrep: no-direct-persons-db-orm
    _seed_group_type_mapping_into_fake(mapping)


# ── Public helpers: Cohort membership ────────────────────────────────


def add_cohort_members(cohort: Cohort, persons: list[Person]) -> None:
    """Add persons to a cohort in Postgres and seed the personhog fake."""
    from products.cohorts.backend.models.cohort import CohortPeople  # noqa: PLC0415

    for person in persons:
        CohortPeople.objects.get_or_create(  # nosemgrep: no-direct-persons-db-orm
            cohort_id=cohort.pk,
            person_id=person.pk,
            defaults={"version": 0},
        )
        _seed_cohort_member_into_fake(cohort.pk, person.pk)


def remove_cohort_members(cohort: Cohort, persons: list[Person]) -> None:
    """Remove persons from a cohort in Postgres and the personhog fake."""
    from products.cohorts.backend.models.cohort import CohortPeople  # noqa: PLC0415

    for person in persons:
        CohortPeople.objects.filter(  # nosemgrep: no-direct-persons-db-orm
            cohort_id=cohort.pk, person_id=person.pk
        ).delete()
        _remove_cohort_member_from_fake(cohort.pk, person.pk)
