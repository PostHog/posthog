"""Test-only wiring that routes person/group reads through the in-memory personhog fake.

Production removed the ORM fallback from person and group data access, so those reads
now go through personhog or raise. In the test suite we activate ``FakePersonHogClient``
globally (see the autouse fixture in the root ``conftest.py``) and mirror rows created
via the ORM into it, so subsequent reads resolve.

This is a thin write-mirror of the test DB into the fake — every person / group /
group-type-mapping written by a test is copied into the fake. It does NOT reimplement
the personhog backend; the fake's own read logic is used unchanged.

The mirror is bidirectional: ``MirroringFakePersonHogClient`` also writes personhog
*writes* (person deletes, cohort membership, version floors) back into the ORM, so tests
that assert on the Postgres DB after such a write keep passing now that the ORM fallback
is gone.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from unittest.mock import patch

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.models import Group, GroupTypeMapping, Person, PersonDistinctId
from posthog.personhog_client.fake_client import FakePersonHogClient

from products.cohorts.backend.models.cohort import CohortPeople

if TYPE_CHECKING:
    from collections.abc import Iterator

    from posthog.personhog_client.proto.generated.personhog.types.v1 import cohort_pb2, person_pb2

# The fake activated by the currently-running test (set by ``activate_personhog_fake``).
# ``None`` outside a test, which makes the signal mirrors below no-ops.
_active_fake: FakePersonHogClient | None = None


def set_active_fake(fake: FakePersonHogClient | None) -> None:
    global _active_fake
    _active_fake = fake


class MirroringFakePersonHogClient(FakePersonHogClient):
    """``FakePersonHogClient`` that also writes back to the Postgres test DB.

    The autouse fixture mirrors ORM *reads* through the fake. But production removed the
    ORM fallback, so personhog *writes* (deletes, cohort membership, version floors) now
    only mutate the in-memory fake. Many tests still assert on the ORM after such a write
    (e.g. ``Person.objects.filter(...).count() == 0`` or ``Person.objects.filter(cohort__id=...)``),
    which used to pass because the ORM fallback performed the same write. Mirror these
    writes back into the ORM so those assertions hold. Reads still come from the fake's
    own logic, unchanged.
    """

    def delete_persons(
        self, request: person_pb2.DeletePersonsRequest, timeout: float | None = None
    ) -> person_pb2.DeletePersonsResponse:
        response = super().delete_persons(request, timeout=timeout)
        if request.person_uuids:
            person_ids = list(
                Person.objects.filter(  # nosemgrep: no-direct-persons-db-orm
                    team_id=request.team_id, uuid__in=list(request.person_uuids)
                ).values_list("pk", flat=True)
            )
            if person_ids:
                # ``_raw_delete`` issues a plain ``DELETE ... WHERE`` and skips Django's cascade
                # collector, which would otherwise walk CohortPeople -> Cohort and join the
                # ``posthog_cohort`` table that lives in the main DB, not the persons DB. Delete
                # children first, scoped by person_id (no cross-table/cross-DB joins).
                cohort_people = CohortPeople.objects.filter(
                    person_id__in=person_ids
                )  # nosemgrep: no-direct-persons-db-orm
                cohort_people._raw_delete(cohort_people.db)
                distinct_ids = PersonDistinctId.objects.filter(
                    person_id__in=person_ids
                )  # nosemgrep: no-direct-persons-db-orm
                distinct_ids._raw_delete(distinct_ids.db)
                persons = Person.objects.filter(
                    team_id=request.team_id, pk__in=person_ids
                )  # nosemgrep: no-direct-persons-db-orm
                persons._raw_delete(persons.db)
        return response

    def insert_cohort_members(
        self, request: cohort_pb2.InsertCohortMembersRequest, timeout: float | None = None
    ) -> cohort_pb2.InsertCohortMembersResponse:
        response = super().insert_cohort_members(request, timeout=timeout)
        existing = set(
            CohortPeople.objects.filter(  # nosemgrep: no-direct-persons-db-orm
                cohort_id=request.cohort_id, person_id__in=list(request.person_ids)
            ).values_list("person_id", flat=True)
        )
        new_rows = [
            CohortPeople(cohort_id=request.cohort_id, person_id=pid, version=request.version)
            for pid in request.person_ids
            if pid not in existing
        ]
        if new_rows:
            CohortPeople.objects.bulk_create(new_rows)  # nosemgrep: no-direct-persons-db-orm
        return response

    def delete_cohort_member(
        self, request: cohort_pb2.DeleteCohortMemberRequest, timeout: float | None = None
    ) -> cohort_pb2.DeleteCohortMemberResponse:
        response = super().delete_cohort_member(request, timeout=timeout)
        CohortPeople.objects.filter(  # nosemgrep: no-direct-persons-db-orm
            cohort_id=request.cohort_id, person_id=request.person_id
        ).delete()  # nosemgrep: no-direct-persons-db-orm
        return response

    def delete_cohort_members_bulk(
        self, request: cohort_pb2.DeleteCohortMembersBulkRequest, timeout: float | None = None
    ) -> cohort_pb2.DeleteCohortMembersBulkResponse:
        response = super().delete_cohort_members_bulk(request, timeout=timeout)
        CohortPeople.objects.filter(  # nosemgrep: no-direct-persons-db-orm
            cohort_id__in=list(request.cohort_ids)
        ).delete()  # nosemgrep: no-direct-persons-db-orm
        return response

    def set_person_distinct_id_version_floor(
        self, request: person_pb2.SetPersonDistinctIdVersionFloorRequest, timeout: float | None = None
    ) -> person_pb2.SetPersonDistinctIdVersionFloorResponse:
        response = super().set_person_distinct_id_version_floor(request, timeout=timeout)
        PersonDistinctId.objects.filter(  # nosemgrep: no-direct-persons-db-orm
            team_id=request.team_id, distinct_id=request.distinct_id, version__lt=request.min_version
        ).update(version=request.min_version)  # nosemgrep: no-direct-persons-db-orm
        return response

    def set_person_version_floor(
        self, request: person_pb2.SetPersonVersionFloorRequest, timeout: float | None = None
    ) -> person_pb2.SetPersonVersionFloorResponse:
        response = super().set_person_version_floor(request, timeout=timeout)
        Person.objects.filter(  # nosemgrep: no-direct-persons-db-orm
            team_id=request.team_id, pk=request.person_id, version__lt=request.min_version
        ).update(version=request.min_version)  # nosemgrep: no-direct-persons-db-orm
        return response


@contextmanager
def activate_personhog_fake() -> Iterator[FakePersonHogClient]:
    """Activate the personhog fake for the duration of a test.

    Patches ``get_personhog_client`` to a mirroring fake and registers it as the mirror
    target so ORM writes during the test are copied into it (and personhog writes are
    copied back into the ORM).
    """
    fake = MirroringFakePersonHogClient()
    with patch("posthog.personhog_client.client.get_personhog_client", return_value=fake):
        set_active_fake(fake)
        try:
            yield fake
        finally:
            set_active_fake(None)


def _created_at_ms(value: object) -> int:
    return int(value.timestamp() * 1000) if value else 0  # type: ignore[attr-defined]


def _seed_person(
    fake: FakePersonHogClient,
    person: Person,
    distinct_ids: list[str],
    distinct_id_versions: dict[str, int] | None = None,
    created_at_ms: int | None = None,
) -> None:
    # Idempotent: ``add_person`` overwrites the person record but appends distinct ids,
    # so only hand it the ids the fake hasn't already mirrored for this person.
    # Coerce to str: the ORM stores distinct ids in a CharField (so tests may pass ints),
    # but the fake builds protobuf messages whose distinct_id field rejects non-strings.
    key = (person.team_id, person.pk)
    existing = {d.distinct_id for d in fake._distinct_ids.get(key, [])}
    new_distinct_ids = [str(d) for d in distinct_ids if str(d) not in existing]
    fake.add_person(
        team_id=person.team_id,
        person_id=person.pk,
        uuid=str(person.uuid),
        properties=person.properties or {},
        is_identified=person.is_identified,
        created_at=created_at_ms if created_at_ms is not None else _created_at_ms(person.created_at),
        distinct_ids=new_distinct_ids,
        distinct_id_versions=distinct_id_versions,
    )


def seed_persons_from_mapping(person_mapping: dict[str, Person]) -> None:
    """Seed the active fake from a ``{distinct_id: Person}`` mapping.

    Used by ``flush_persons_and_events`` to cover the ``bulk_create`` path, which
    bypasses Django signals and so isn't caught by the mirrors below.
    """
    fake = _active_fake
    if fake is None or not person_mapping:
        return
    by_person: dict[int, tuple[Person, list[str]]] = {}
    for distinct_id, person in person_mapping.items():
        _, distinct_ids = by_person.setdefault(person.pk, (person, []))
        distinct_ids.append(distinct_id)

    # ``bulk_create`` assigns ``created_at`` (auto_now_add) from per-object ``now()`` calls
    # microseconds apart, which collapse to the same millisecond once truncated by
    # ``_created_at_ms``. The persons-list / actors read paths sort by ``(-created_at, uuid)``,
    # so a created_at tie silently reverses the intended creation order (the ORM read path on
    # master kept microsecond precision). Re-spread the mirrored created_at by primary key
    # (which increases with creation order, in lockstep with the deterministic test uuids) so
    # the fake preserves creation order deterministically.
    prev_ms = 0
    for pk in sorted(by_person):
        person, distinct_ids = by_person[pk]
        created_at_ms = max(_created_at_ms(person.created_at), prev_ms + 1)
        prev_ms = created_at_ms
        _seed_person(fake, person, distinct_ids, created_at_ms=created_at_ms)


def _seed_group_type_mapping(fake: FakePersonHogClient, mapping: GroupTypeMapping) -> None:
    # Idempotent: the fake stores mappings in per-project / per-team lists, so drop any
    # existing entry for this index before re-adding.
    for store, store_key in (
        (fake._group_type_mappings_by_project, mapping.project_id),
        (fake._group_type_mappings_by_team, mapping.team_id),
    ):
        existing = store.get(store_key)
        if existing:
            store[store_key] = [m for m in existing if m.group_type_index != mapping.group_type_index]
    fake.add_group_type_mapping(
        project_id=mapping.project_id,
        team_id=mapping.team_id,
        group_type=mapping.group_type,
        group_type_index=mapping.group_type_index,
        id=mapping.pk or 0,
        name_singular=mapping.name_singular or "",
        name_plural=mapping.name_plural or "",
        default_columns=mapping.default_columns or None,
        detail_dashboard_id=mapping.detail_dashboard_id or 0,
        # HogQL emits a created_at-gated group-key override, so the mapping's created_at
        # must survive the round-trip through the fake.
        created_at=_created_at_ms(mapping.created_at),
    )


def _unseed_group_type_mapping(fake: FakePersonHogClient, mapping: GroupTypeMapping) -> None:
    for store, store_key in (
        (fake._group_type_mappings_by_project, mapping.project_id),
        (fake._group_type_mappings_by_team, mapping.team_id),
    ):
        existing = store.get(store_key)
        if existing:
            store[store_key] = [m for m in existing if m.group_type_index != mapping.group_type_index]


def _unseed_person(fake: FakePersonHogClient, person: Person) -> None:
    key = (person.team_id, person.pk)
    dids = fake._distinct_ids.pop(key, [])
    fake._persons_by_id.pop(key, None)
    fake._persons_by_uuid.pop((person.team_id, str(person.uuid)), None)
    for did in dids:
        fake._persons_by_distinct_id.pop((person.team_id, did.distinct_id), None)


@receiver(post_save, sender=Person)
def _mirror_person(sender: type[Person], instance: Person, **kwargs: object) -> None:
    fake = _active_fake
    if fake is None:
        return
    _seed_person(fake, instance, [])


@receiver(post_save, sender=PersonDistinctId)
def _mirror_distinct_id(sender: type[PersonDistinctId], instance: PersonDistinctId, **kwargs: object) -> None:
    fake = _active_fake
    if fake is None:
        return
    # Preserve the PersonDistinctId version: delete_person reads it back via personhog to
    # compute the ClickHouse tombstone version (version + 100), so a dropped version breaks
    # version-sensitive delete assertions.
    distinct_id = str(instance.distinct_id)
    _seed_person(fake, instance.person, [distinct_id], {distinct_id: int(instance.version or 0)})


@receiver(post_save, sender=Group)
def _mirror_group(sender: type[Group], instance: Group, **kwargs: object) -> None:
    fake = _active_fake
    if fake is None:
        return
    fake.add_group(
        team_id=instance.team_id,
        group_type_index=instance.group_type_index,
        group_key=instance.group_key,
        group_properties=instance.group_properties or {},
        id=instance.pk or 0,
        created_at=_created_at_ms(instance.created_at),
        version=instance.version or 0,
    )


@receiver(post_save, sender=GroupTypeMapping)
def _mirror_group_type_mapping(sender: type[GroupTypeMapping], instance: GroupTypeMapping, **kwargs: object) -> None:
    fake = _active_fake
    if fake is None:
        return
    _seed_group_type_mapping(fake, instance)


@receiver(post_delete, sender=Person)
def _unmirror_person(sender: type[Person], instance: Person, **kwargs: object) -> None:
    fake = _active_fake
    if fake is None:
        return
    _unseed_person(fake, instance)


@receiver(post_delete, sender=PersonDistinctId)
def _unmirror_distinct_id(sender: type[PersonDistinctId], instance: PersonDistinctId, **kwargs: object) -> None:
    fake = _active_fake
    if fake is None:
        return
    # Match the str coercion applied when seeding (the ORM CharField may hold an int).
    distinct_id = str(instance.distinct_id)
    key = (instance.person.team_id, instance.person.pk)
    dids = fake._distinct_ids.get(key)
    if dids is not None:
        fake._distinct_ids[key] = [d for d in dids if d.distinct_id != distinct_id]
    fake._persons_by_distinct_id.pop((instance.person.team_id, distinct_id), None)


@receiver(post_delete, sender=Group)
def _unmirror_group(sender: type[Group], instance: Group, **kwargs: object) -> None:
    fake = _active_fake
    if fake is None:
        return
    fake._groups.pop((instance.team_id, instance.group_type_index, instance.group_key), None)


@receiver(post_delete, sender=GroupTypeMapping)
def _unmirror_group_type_mapping(sender: type[GroupTypeMapping], instance: GroupTypeMapping, **kwargs: object) -> None:
    fake = _active_fake
    if fake is None:
        return
    _unseed_group_type_mapping(fake, instance)
