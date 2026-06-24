"""Personhog fake activation and write-mirroring for tests.

activate_personhog_fake() patches get_personhog_client and use_personhog so all
person/group reads route through a FakePersonHogClient.

MirroringFakePersonHogClient mirrors personhog writes (deletes, version floors,
cohort membership) back to Postgres for tests that still assert ORM state.

Transitional: once the ORM fallback and persons DB connection are removed,
MirroringFakePersonHogClient can be deleted.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import TYPE_CHECKING

from unittest.mock import patch

from django.db import connections, router

from posthog.personhog_client.fake_client import FakePersonHogClient
from posthog.personhog_client.proto.generated.personhog.types.v1 import cohort_pb2, group_pb2, person_pb2

if TYPE_CHECKING:
    pass


_active_fake: FakePersonHogClient | None = None


def set_active_fake(fake: FakePersonHogClient | None) -> None:
    global _active_fake
    _active_fake = fake


def get_active_fake() -> FakePersonHogClient:
    assert _active_fake is not None, "get_active_fake() called outside activate_personhog_fake() context"
    return _active_fake


def _persons_db_alias() -> str:
    from posthog.models.person import Person as _Person  # noqa: PLC0415

    return router.db_for_write(_Person) or "default"


@contextmanager
def activate_personhog_fake():
    """Activate a MirroringFakePersonHogClient for the duration of a test.

    Patches get_personhog_client and use_personhog so all reads route through
    the fake.  Test helpers in posthog.test.persons seed the fake explicitly
    when creating data — no signals are used.
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


# ── MirroringFakePersonHogClient ─────────────────────────────────────


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
        import datetime  # noqa: PLC0415

        from posthog.models.group.group import Group as _Group  # noqa: PLC0415

        response = super().create_group(request)
        group_obj, _ = _Group.objects.get_or_create(  # nosemgrep: no-direct-persons-db-orm
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
        response.group.id = group_obj.pk
        return response

    def delete_persons(
        self,
        request: person_pb2.DeletePersonsRequest,
        timeout: float | None = None,
    ) -> person_pb2.DeletePersonsResponse:
        from posthog.models.person import Person as _Person  # noqa: PLC0415

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
        from posthog.models.person import Person as _Person  # noqa: PLC0415

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
        from products.cohorts.backend.models.cohort import CohortPeople  # noqa: PLC0415

        response = super().insert_cohort_members(request, timeout)
        if response.inserted_count > 0:
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
