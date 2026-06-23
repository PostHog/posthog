"""Write-mirror for personhog fake in tests.

Signal receivers copy ORM writes into the active FakePersonHogClient so reads
through personhog return data created via the ORM.  MirroringFakePersonHogClient
mirrors personhog writes (deletes, version floors, cohort membership) back to
Postgres for tests that still assert ORM state.

Transitional: once the ORM fallback and persons DB connection are removed, both
the signal mirroring and MirroringFakePersonHogClient can be deleted.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import TYPE_CHECKING

from unittest.mock import patch

from django.db import connections, router
from django.db.models.signals import m2m_changed, post_delete, post_save

from posthog.personhog_client.fake_client import FakePersonHogClient
from posthog.personhog_client.proto.generated.personhog.types.v1 import cohort_pb2, group_pb2, person_pb2

if TYPE_CHECKING:
    from datetime import datetime

    from posthog.models.group.group import Group
    from posthog.models.group_type_mapping import GroupTypeMapping
    from posthog.models.person import Person, PersonDistinctId

    from products.cohorts.backend.models.cohort import Cohort, CohortPeople


_active_fake: FakePersonHogClient | None = None


def _datetime_to_ms(dt: datetime | None) -> int:
    if dt is None:
        return 0
    return int(dt.timestamp() * 1000)


def set_active_fake(fake: FakePersonHogClient | None) -> None:
    global _active_fake
    _active_fake = fake


def get_active_fake() -> FakePersonHogClient:
    assert _active_fake is not None, "get_active_fake() called outside activate_personhog_fake() context"
    return _active_fake


@contextmanager
def activate_personhog_fake():
    """Activate a MirroringFakePersonHogClient for the duration of a test.

    Patches get_personhog_client and use_personhog so all reads route through
    the fake.  Signal receivers copy ORM writes into the fake automatically.
    """
    fake = MirroringFakePersonHogClient()
    set_active_fake(fake)
    with (
        patch("posthog.personhog_client.client.get_personhog_client", return_value=fake),
        patch("posthog.personhog_client.gate.use_personhog", return_value=True),
    ):
        try:
            yield fake
        finally:
            set_active_fake(None)


# ── Seeding helpers ──────────────────────────────────────────────────


def _seed_person(
    fake: FakePersonHogClient,
    person: Person,
    distinct_ids: list[str],
    *,
    created_at_ms: int | None = None,
) -> None:
    """Copy a person into the fake.  Idempotent — skips distinct_ids already present."""
    existing_dids = {d.distinct_id for d in fake._distinct_ids.get((person.team_id, person.pk), [])}
    new_dids = [str(did) for did in distinct_ids if str(did) not in existing_dids]

    distinct_id_versions: dict[str, int] = {}
    if new_dids:
        from posthog.models.person import PersonDistinctId

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

    # add_person overwrites the proto in _persons_by_id/_persons_by_uuid but
    # leaves stale refs in _persons_by_distinct_id for previously-added dids.
    for did_with_ver in fake._distinct_ids.get((person.team_id, person.pk), []):
        fake._persons_by_distinct_id[(person.team_id, did_with_ver.distinct_id)] = person_proto


def seed_persons_from_mapping(person_mapping: dict[str, Person]) -> None:
    """Seed the active fake from bulk_create_persons output.

    bulk_create bypasses post_save signals, so this must be called explicitly.
    Timestamps are spread by pk so persons created in the same millisecond
    keep deterministic creation-order in list/actors reads.
    """
    if _active_fake is None:
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
        _seed_person(_active_fake, person, dids, created_at_ms=created_at_ms)


def _seed_group_type_mapping(fake: FakePersonHogClient, instance: GroupTypeMapping) -> None:
    """Idempotent mirror for group type mappings — remove + re-add to avoid duplication."""
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


# ── Signal receivers ─────────────────────────────────────────────────
# Connected at import time but no-op when _active_fake is None.


def _on_person_post_save(sender: type, instance: Person, **kwargs: object) -> None:
    if _active_fake is None:
        return
    person_proto = _active_fake.add_person(
        team_id=instance.team_id,
        person_id=instance.pk,
        uuid=str(instance.uuid),
        properties=instance.properties or {},
        created_at=_datetime_to_ms(instance.created_at),
        version=instance.version or 0,
        is_identified=instance.is_identified,
    )
    # Update distinct_id mappings to point to the fresh proto object
    for did_with_ver in _active_fake._distinct_ids.get((instance.team_id, instance.pk), []):
        _active_fake._persons_by_distinct_id[(instance.team_id, did_with_ver.distinct_id)] = person_proto


def _on_person_distinct_id_post_save(sender: type, instance: PersonDistinctId, **kwargs: object) -> None:
    if _active_fake is None:
        return
    fake = _active_fake
    did = str(instance.distinct_id)
    version = instance.version or 0
    team_id = instance.team_id
    person_id = instance.person_id

    person_proto = fake._persons_by_id.get((team_id, person_id))
    if person_proto is None:
        _seed_person(fake, instance.person, [did])
        return

    existing_dids = {d.distinct_id for d in fake._distinct_ids.get((team_id, person_id), [])}
    if did in existing_dids:
        return

    fake._persons_by_distinct_id[(team_id, did)] = person_proto
    fake._distinct_ids.setdefault((team_id, person_id), []).append(
        person_pb2.DistinctIdWithVersion(distinct_id=did, version=version)
    )


def _on_group_post_save(sender: type, instance: Group, **kwargs: object) -> None:
    if _active_fake is None:
        return
    _active_fake.add_group(
        team_id=instance.team_id,
        group_type_index=instance.group_type_index,
        group_key=instance.group_key,
        group_properties=instance.group_properties or {},
        id=instance.pk,
        created_at=_datetime_to_ms(instance.created_at),
        version=instance.version or 0,
    )


def _on_group_type_mapping_post_save(sender: type, instance: GroupTypeMapping, **kwargs: object) -> None:
    if _active_fake is None:
        return
    _seed_group_type_mapping(_active_fake, instance)


# ── Cohort membership signal receivers ──────────────────────────────


def _on_cohort_people_post_save(sender: type, instance: CohortPeople, **kwargs: object) -> None:
    if _active_fake is None:
        return
    cohort_id = instance.cohort_id
    person_id = instance.person_id
    if (cohort_id, person_id) not in _active_fake._cohort_members:
        _active_fake.add_cohort_membership(person_id=person_id, cohort_id=cohort_id, is_member=True)


def _on_cohort_people_post_delete(sender: type, instance: CohortPeople, **kwargs: object) -> None:
    if _active_fake is None:
        return
    cohort_id = instance.cohort_id
    person_id = instance.person_id
    _active_fake._cohort_members.pop((cohort_id, person_id), None)
    memberships = _active_fake._cohort_memberships.get(person_id)
    if memberships is not None:
        _active_fake._cohort_memberships[person_id] = [m for m in memberships if m.cohort_id != cohort_id]


def _on_cohort_people_m2m_changed(
    sender: type, instance: Cohort, action: str, pk_set: set[int] | None, **kwargs: object
) -> None:
    """Handle cohort.people.add() / .remove() which fires m2m_changed, not post_save."""
    if _active_fake is None or pk_set is None:
        return

    from products.cohorts.backend.models.cohort import CohortPeople as _CP

    if action == "post_add":
        cohort_id = instance.pk
        for cp in _CP.objects.filter(cohort_id=cohort_id, person_id__in=pk_set):  # nosemgrep: no-direct-persons-db-orm
            if (cp.cohort_id, cp.person_id) not in _active_fake._cohort_members:
                _active_fake.add_cohort_membership(person_id=cp.person_id, cohort_id=cp.cohort_id, is_member=True)
    elif action == "post_remove":
        cohort_id = instance.pk
        for person_id in pk_set:
            _active_fake._cohort_members.pop((cohort_id, person_id), None)
            memberships = _active_fake._cohort_memberships.get(person_id)
            if memberships is not None:
                _active_fake._cohort_memberships[person_id] = [m for m in memberships if m.cohort_id != cohort_id]


# Imports here because the module is only loaded during tests (via conftest)
# and Django models are fully available at that point.
from posthog.models.group.group import Group as _Group  # noqa: E402
from posthog.models.group_type_mapping import GroupTypeMapping as _GroupTypeMapping  # noqa: E402
from posthog.models.person import (  # noqa: E402
    Person as _Person,
    PersonDistinctId as _PersonDistinctId,
)

from products.cohorts.backend.models.cohort import (  # noqa: E402
    Cohort as _Cohort,
    CohortPeople as _CohortPeople,
)

post_save.connect(_on_person_post_save, sender=_Person, dispatch_uid="personhog_fake_person")
post_save.connect(_on_person_distinct_id_post_save, sender=_PersonDistinctId, dispatch_uid="personhog_fake_pdi")
post_save.connect(_on_group_post_save, sender=_Group, dispatch_uid="personhog_fake_group")
post_save.connect(_on_group_type_mapping_post_save, sender=_GroupTypeMapping, dispatch_uid="personhog_fake_gtm")
post_save.connect(_on_cohort_people_post_save, sender=_CohortPeople, dispatch_uid="personhog_fake_cp_save")
post_delete.connect(_on_cohort_people_post_delete, sender=_CohortPeople, dispatch_uid="personhog_fake_cp_del")
m2m_changed.connect(_on_cohort_people_m2m_changed, sender=_Cohort.people.through, dispatch_uid="personhog_fake_cp_m2m")


# ── MirroringFakePersonHogClient ─────────────────────────────────────


def _persons_db_alias() -> str:
    return router.db_for_write(_Person) or "default"


class MirroringFakePersonHogClient(FakePersonHogClient):
    """FakePersonHogClient that mirrors writes back to Postgres.

    Transitional: keeps ORM state in sync with personhog-only operations so
    existing tests that assert ORM state continue to pass.  Will be removed
    when the persons DB connection is dropped.
    """

    def create_group(
        self,
        request: group_pb2.CreateGroupRequest,
    ) -> group_pb2.CreateGroupResponse:
        import datetime

        response = super().create_group(request)
        _Group.objects.get_or_create(  # nosemgrep: no-direct-persons-db-orm
            team_id=request.team_id,
            group_type_index=request.group_type_index,
            group_key=request.group_key,
            defaults={
                "group_properties": json.loads(request.group_properties) if request.group_properties else {},
                "created_at": datetime.datetime.fromtimestamp(request.created_at / 1000, tz=datetime.UTC)
                if request.created_at
                else None,
                "version": 0,
            },
        )
        return response

    def delete_persons(
        self,
        request: person_pb2.DeletePersonsRequest,
        timeout: float | None = None,
    ) -> person_pb2.DeletePersonsResponse:
        response = super().delete_persons(request, timeout)
        if response.deleted_count > 0:
            uuids = [str(u) for u in request.person_uuids]
            db = _persons_db_alias()
            table = _Person._meta.db_table
            with connections[db].cursor() as cursor:
                placeholders = ", ".join(["%s"] * len(uuids))
                cursor.execute(
                    f"DELETE FROM posthog_persondistinctid WHERE person_id IN "
                    f"(SELECT id FROM {table} WHERE team_id = %s AND uuid IN ({placeholders}))",
                    [request.team_id, *uuids],
                )
                cursor.execute(
                    f"DELETE FROM {table} WHERE team_id = %s AND uuid IN ({placeholders})",
                    [request.team_id, *uuids],
                )
        return response

    def set_person_version_floor(
        self,
        request: person_pb2.SetPersonVersionFloorRequest,
        timeout: float | None = None,
    ) -> person_pb2.SetPersonVersionFloorResponse:
        response = super().set_person_version_floor(request, timeout)
        if response.updated:
            db = _persons_db_alias()
            table = _Person._meta.db_table
            with connections[db].cursor() as cursor:
                cursor.execute(
                    f"UPDATE {table} SET version = %s "
                    f"WHERE team_id = %s AND id = %s AND (version IS NULL OR version < %s)",
                    [request.min_version, request.team_id, request.person_id, request.min_version],
                )
        return response

    def set_person_distinct_id_version_floor(
        self,
        request: person_pb2.SetPersonDistinctIdVersionFloorRequest,
        timeout: float | None = None,
    ) -> person_pb2.SetPersonDistinctIdVersionFloorResponse:
        response = super().set_person_distinct_id_version_floor(request, timeout)
        db = _persons_db_alias()
        with connections[db].cursor() as cursor:
            cursor.execute(
                "UPDATE posthog_persondistinctid SET version = %s "
                "WHERE team_id = %s AND distinct_id = %s AND (version IS NULL OR version < %s)",
                [request.min_version, request.team_id, request.distinct_id, request.min_version],
            )
        return response

    def insert_cohort_members(
        self,
        request: cohort_pb2.InsertCohortMembersRequest,
        timeout: float | None = None,
    ) -> cohort_pb2.InsertCohortMembersResponse:
        response = super().insert_cohort_members(request, timeout)
        if response.inserted_count > 0:
            from products.cohorts.backend.models.cohort import CohortPeople

            for pid in request.person_ids:
                CohortPeople.objects.get_or_create(
                    cohort_id=request.cohort_id,
                    person_id=pid,
                    defaults={"version": 0},
                )
        return response

    def delete_cohort_member(
        self,
        request: cohort_pb2.DeleteCohortMemberRequest,
        timeout: float | None = None,
    ) -> cohort_pb2.DeleteCohortMemberResponse:
        response = super().delete_cohort_member(request, timeout)
        if response.deleted:
            db = _persons_db_alias()
            with connections[db].cursor() as cursor:
                cursor.execute(
                    "DELETE FROM posthog_cohortpeople WHERE cohort_id = %s AND person_id = %s",
                    [request.cohort_id, request.person_id],
                )
        return response

    def delete_cohort_members_bulk(
        self,
        request: cohort_pb2.DeleteCohortMembersBulkRequest,
        timeout: float | None = None,
    ) -> cohort_pb2.DeleteCohortMembersBulkResponse:
        response = super().delete_cohort_members_bulk(request, timeout)
        if response.deleted_count > 0:
            cohort_ids = list(request.cohort_ids)
            if cohort_ids:
                placeholders = ", ".join(["%s"] * len(cohort_ids))
                db = _persons_db_alias()
                with connections[db].cursor() as cursor:
                    cursor.execute(
                        f"DELETE FROM posthog_cohortpeople WHERE cohort_id IN ({placeholders})",
                        cohort_ids,
                    )
        return response
