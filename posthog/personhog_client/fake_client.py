"""Fake PersonHogClient for tests.

Usage in tests::

    from posthog.personhog_client.fake_client import fake_personhog_client

    def test_something(self):
        with fake_personhog_client() as fake:
            fake.add_group_type_mapping(project_id=1, group_type="org", group_type_index=0)
            # code under test calls get_personhog_client() and gets the fake
            result = get_group_types_for_project(1)
            assert len(result) == 1

The fake uses real proto message classes so that converters / serialization
boundaries are exercised end-to-end.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

from unittest.mock import patch

import grpc
from personhog.lifecycle.v1 import lifecycle_pb2
from personhog.types.v1 import cohort_pb2, feature_flag_pb2, group_pb2, person_pb2

from posthog.dataclasses import frozen
from posthog.models.person.missing_person import uuidFromDistinctId
from posthog.personhog_client.interceptor import SEMANTIC_REFUSAL_METADATA_KEY
from posthog.utils import is_anonymous_id


@frozen(kw_only=False)
class _Call:
    method: str
    request: Any
    response: Any = None
    # The per-call deadline the caller passed, for the lifecycle sagas; None means the channel default.
    timeout: float | None = None


class _FakeRpcError(grpc.RpcError):
    """A failed call the way grpcio raises one: status, details and trailing metadata are methods."""

    def __init__(
        self, code: grpc.StatusCode, details: str, trailing_metadata: Sequence[tuple[str, str | bytes]] = ()
    ) -> None:
        super().__init__(details)
        self._code = code
        self._details = details
        self._trailing_metadata = trailing_metadata

    def code(self) -> grpc.StatusCode:
        return self._code

    def details(self) -> str:
        return self._details

    def trailing_metadata(self) -> Sequence[tuple[str, str | bytes]]:
        return self._trailing_metadata


def _order_identified_first(
    dids: list[person_pb2.DistinctIdWithVersion],
) -> list[person_pb2.DistinctIdWithVersion]:
    """Mirror the server-side ordering of limited distinct_id fetches (personhog-replica
    orders anonymous-shaped ids last before applying LIMIT, so identified ids survive)."""
    return sorted(dids, key=lambda d: is_anonymous_id(d.distinct_id))


# The replica's row budget when a request leaves max_rows at 0.
DELETE_TOMBSTONED_DEFAULT_ROWS = 1000

# The replica's cap on keys per version floor request.
VERSION_RPC_MAX_KEYS = 250

# The replica's cap on distinct ids across all persons in one restore request.
RESTORE_MAX_DISTINCT_IDS = 1000

# The identity server's cap on person ids per lifecycle DeletePersons request.
LIFECYCLE_DELETE_MAX_PERSON_IDS = 250

# team_id is narrowed to i32 server-side.
_MAX_TEAM_ID = 2**31 - 1


class _FakeLifecycleClient:
    """The fake's ``lifecycle`` namespace; the saga state lives on the fake itself."""

    def __init__(self, fake: FakePersonHogClient) -> None:
        self._fake = fake

    @property
    def configured(self) -> bool:
        return True

    def delete_persons(
        self, request: lifecycle_pb2.DeletePersonsRequest, timeout: float | None = None
    ) -> lifecycle_pb2.DeletePersonsResponse:
        return self._fake._lifecycle_delete_persons(request, timeout)


class FakePersonHogClient:
    """In-memory fake that implements the same interface as PersonHogClient.

    Stores data as real proto messages and returns real proto responses,
    so the full converter pipeline is exercised.
    """

    def __init__(self) -> None:
        self.calls: list[_Call] = []
        self.lifecycle = _FakeLifecycleClient(self)

        # keyed by (team_id, person_id)
        self._persons_by_id: dict[tuple[int, int], person_pb2.Person] = {}
        # keyed by (team_id, uuid)
        self._persons_by_uuid: dict[tuple[int, str], person_pb2.Person] = {}
        # keyed by (team_id, distinct_id)
        self._persons_by_distinct_id: dict[tuple[int, str], person_pb2.Person] = {}
        # keyed by (team_id, person_id) -> list of DistinctIdWithVersion
        self._distinct_ids: dict[tuple[int, int], list[person_pb2.DistinctIdWithVersion]] = {}
        # keyed by (team_id, distinct_id): mappings tombstoned alongside their person
        self._tombstoned_distinct_ids: set[tuple[int, str]] = set()
        self.tombstone_queue: dict[tuple[int, str], int] = {}
        self.tombstone_queued_at_ms: dict[tuple[int, str], int] = {}
        # Mirrors the replica's TOMBSTONED_DELETE_MAX_ROWS clamp. The fake tracks distinct ids
        # only, so the row budget counts them alone.
        self.tombstoned_delete_max_rows = 5000

        # by op_id: the frozen request (team, person ids as sent) and the recorded response
        self._lifecycle_ops: dict[str, tuple[int, tuple[int, ...], lifecycle_pb2.DeletePersonsResponse]] = {}
        # (team_id, person_id) held by another live lifecycle op
        self._lifecycle_marks: set[tuple[int, int]] = set()
        self._lifecycle_versionless: set[tuple[int, int]] = set()

        # keyed by project_id -> list of GroupTypeMapping
        self._group_type_mappings_by_project: dict[int, list[group_pb2.GroupTypeMapping]] = {}
        # keyed by team_id -> list of GroupTypeMapping
        self._group_type_mappings_by_team: dict[int, list[group_pb2.GroupTypeMapping]] = {}

        # keyed by (team_id, group_type_index, group_key) -> Group
        self._groups: dict[tuple[int, int, str], group_pb2.Group] = {}

        # keyed by person_id -> list of CohortMembership
        self._cohort_memberships: dict[int, list[cohort_pb2.CohortMembership]] = {}
        # keyed by (cohort_id, person_id) -> True
        self._cohort_members: dict[tuple[int, int], bool] = {}

        # synthetic ids for persons created by split_person and ensure_person_version_floors
        self._next_split_person_id = 1_000_000_000

        # monotonic counter for distinct ID row IDs
        self._next_distinct_id_row_id = 1

    # ── Builder methods ──────────────────────────────────────────────

    def add_person(
        self,
        *,
        team_id: int,
        person_id: int,
        uuid: str = "",
        properties: dict | None = None,
        created_at: int = 0,
        version: int = 0,
        is_identified: bool = False,
        is_user_id: bool | None = None,
        distinct_ids: list[str] | None = None,
        distinct_id_versions: dict[str, int] | None = None,
        last_seen_at: int = 0,
        is_deleted: bool = False,
        tombstoned_distinct_ids: list[str] | None = None,
    ) -> person_pb2.Person:
        person = person_pb2.Person(
            id=person_id,
            uuid=uuid,
            team_id=team_id,
            properties=json.dumps(properties or {}).encode(),
            created_at=created_at,
            version=version,
            is_identified=is_identified,
            last_seen_at=last_seen_at,
            is_deleted=is_deleted,
        )
        if is_user_id is not None:
            person.is_user_id = is_user_id
        self._persons_by_id[(team_id, person_id)] = person
        if uuid:
            self._persons_by_uuid[(team_id, uuid)] = person
        for did in distinct_ids or []:
            self._persons_by_distinct_id[(team_id, did)] = person
            # A re-added mapping is live again, as a revival upsert makes it in the replica.
            self._tombstoned_distinct_ids.discard((team_id, did))
            self._distinct_ids.setdefault((team_id, person_id), []).append(
                person_pb2.DistinctIdWithVersion(distinct_id=did, version=(distinct_id_versions or {}).get(did, 0))
            )
        for did in tombstoned_distinct_ids or []:
            self._tombstoned_distinct_ids.add((team_id, did))
        return person

    def add_group_type_mapping(
        self,
        *,
        project_id: int,
        team_id: int = 0,
        group_type: str,
        group_type_index: int,
        id: int = 0,
        name_singular: str = "",
        name_plural: str = "",
        default_columns: list[str] | None = None,
        detail_dashboard_id: int = 0,
        created_at: int = 0,
    ) -> group_pb2.GroupTypeMapping:
        mapping = group_pb2.GroupTypeMapping(
            id=id,
            team_id=team_id,
            project_id=project_id,
            group_type=group_type,
            group_type_index=group_type_index,
            name_singular=name_singular,
            name_plural=name_plural,
            default_columns=json.dumps(default_columns).encode() if default_columns else b"",
            detail_dashboard_id=detail_dashboard_id,
            created_at=created_at,
        )
        self._group_type_mappings_by_project.setdefault(project_id, []).append(mapping)
        if team_id:
            self._group_type_mappings_by_team.setdefault(team_id, []).append(mapping)
        return mapping

    def add_group(
        self,
        *,
        team_id: int,
        group_type_index: int,
        group_key: str,
        group_properties: dict | None = None,
        id: int = 0,
        created_at: int = 0,
        version: int = 0,
    ) -> group_pb2.Group:
        group = group_pb2.Group(
            id=id,
            team_id=team_id,
            group_type_index=group_type_index,
            group_key=group_key,
            group_properties=json.dumps(group_properties or {}).encode(),
            created_at=created_at,
            version=version,
        )
        self._groups[(team_id, group_type_index, group_key)] = group
        return group

    def hold_lifecycle_mark(self, *, team_id: int, person_id: int) -> None:
        """Make a person look held by another live lifecycle op, so a delete reports SKIPPED_CONFLICT."""
        self._lifecycle_marks.add((team_id, person_id))

    def release_lifecycle_mark(self, *, team_id: int, person_id: int) -> None:
        self._lifecycle_marks.discard((team_id, person_id))

    def omit_lifecycle_person_version(self, *, team_id: int, person_id: int) -> None:
        """Answer a delete of this person like an op recorded by a build that stored no tombstone version."""
        self._lifecycle_versionless.add((team_id, person_id))

    def add_cohort_membership(self, *, person_id: int, cohort_id: int, is_member: bool = True) -> None:
        self._cohort_memberships.setdefault(person_id, []).append(
            cohort_pb2.CohortMembership(cohort_id=cohort_id, is_member=is_member)
        )
        if is_member:
            self._cohort_members[(cohort_id, person_id)] = True

    # ── PersonHogClient interface ────────────────────────────────────

    def close(self) -> None:
        pass

    # Reads mirror the replica, which filters tombstoned persons and mappings out of every person
    # lookup. The tombstone RPCs below read the internal dicts, so they still see the tombstones.
    @staticmethod
    def _live(person: person_pb2.Person | None) -> person_pb2.Person | None:
        return None if person is None or person.is_deleted else person

    def _live_by_distinct_id(self, team_id: int, distinct_id: str) -> person_pb2.Person | None:
        if (team_id, distinct_id) in self._tombstoned_distinct_ids:
            return None
        return self._live(self._persons_by_distinct_id.get((team_id, distinct_id)))

    def stored_person(self, team_id: int, uuid: str) -> person_pb2.Person | None:
        """The stored row, tombstoned or not, for tests that check what a delete left in place."""
        return self._persons_by_uuid.get((team_id, uuid))

    def stored_person_by_distinct_id(self, team_id: int, distinct_id: str) -> person_pb2.Person | None:
        """The person a stored mapping points at, tombstoned or not."""
        return self._persons_by_distinct_id.get((team_id, distinct_id))

    def get_person(self, request: person_pb2.GetPersonRequest) -> person_pb2.GetPersonResponse:
        self.calls.append(_Call("get_person", request))
        person = self._live(self._persons_by_id.get((request.team_id, request.person_id)))
        return person_pb2.GetPersonResponse(person=person)

    def get_persons(self, request: person_pb2.GetPersonsRequest) -> person_pb2.PersonsResponse:
        self.calls.append(_Call("get_persons", request))
        found = []
        missing = []
        for pid in request.person_ids:
            person = self._live(self._persons_by_id.get((request.team_id, pid)))
            if person:
                found.append(person)
            else:
                missing.append(pid)
        return person_pb2.PersonsResponse(persons=found, missing_ids=missing)

    def get_person_by_uuid(self, request: person_pb2.GetPersonByUuidRequest) -> person_pb2.GetPersonResponse:
        self.calls.append(_Call("get_person_by_uuid", request))
        person = self._live(self._persons_by_uuid.get((request.team_id, request.uuid)))
        return person_pb2.GetPersonResponse(person=person)

    def get_persons_by_uuids(self, request: person_pb2.GetPersonsByUuidsRequest) -> person_pb2.PersonsResponse:
        self.calls.append(_Call("get_persons_by_uuids", request))
        found = []
        missing_ids: list[int] = []
        for uuid in request.uuids:
            person = self._live(self._persons_by_uuid.get((request.team_id, uuid)))
            if person:
                found.append(person)
        return person_pb2.PersonsResponse(persons=found, missing_ids=missing_ids)

    def get_person_by_distinct_id(
        self, request: person_pb2.GetPersonByDistinctIdRequest
    ) -> person_pb2.GetPersonResponse:
        self.calls.append(_Call("get_person_by_distinct_id", request))
        person = self._live_by_distinct_id(request.team_id, request.distinct_id)
        return person_pb2.GetPersonResponse(person=person)

    def get_persons_by_distinct_ids_in_team(
        self, request: person_pb2.GetPersonsByDistinctIdsInTeamRequest
    ) -> person_pb2.PersonsByDistinctIdsInTeamResponse:
        self.calls.append(_Call("get_persons_by_distinct_ids_in_team", request))
        results = []
        for did in request.distinct_ids:
            person = self._live_by_distinct_id(request.team_id, did)
            if person:
                results.append(person_pb2.PersonWithDistinctIds(distinct_id=did, person=person))
        return person_pb2.PersonsByDistinctIdsInTeamResponse(results=results)

    # NOTE: the real RPC returns one result per requested distinct_id (no
    # deduplication by person).  Callers that need unique persons (e.g.
    # _fetch_persons_by_distinct_ids_via_personhog) must deduplicate
    # themselves.

    def get_distinct_ids_for_person(
        self, request: person_pb2.GetDistinctIdsForPersonRequest
    ) -> person_pb2.GetDistinctIdsForPersonResponse:
        self.calls.append(_Call("get_distinct_ids_for_person", request))
        dids = list(self._distinct_ids.get((request.team_id, request.person_id), []))
        limit = request.limit if request.HasField("limit") and request.limit > 0 else None
        has_cursor = request.HasField("cursor_id")
        cursor_id = request.cursor_id if has_cursor else None

        for d in dids:
            if not d.HasField("id"):
                d.id = self._next_distinct_id_row_id
                self._next_distinct_id_row_id += 1

        if has_cursor:
            dids = [d for d in dids if d.id > (cursor_id or 0)]
            dids.sort(key=lambda d: d.id)
            if limit is not None:
                dids = dids[:limit]
        elif limit is not None:
            dids = _order_identified_first(dids)[:limit]

        next_cursor_id = None
        if limit is not None and len(dids) >= limit:
            next_cursor_id = dids[-1].id

        return person_pb2.GetDistinctIdsForPersonResponse(
            distinct_ids=dids,
            next_cursor_id=next_cursor_id,
        )

    def get_distinct_ids_for_persons(
        self, request: person_pb2.GetDistinctIdsForPersonsRequest
    ) -> person_pb2.GetDistinctIdsForPersonsResponse:
        self.calls.append(_Call("get_distinct_ids_for_persons", request))
        limit = (
            request.limit_per_person if request.HasField("limit_per_person") and request.limit_per_person > 0 else None
        )
        results = []
        for pid in request.person_ids:
            dids = self._distinct_ids.get((request.team_id, pid), [])
            if limit is not None:
                dids = _order_identified_first(dids)[:limit]
            results.append(person_pb2.PersonDistinctIds(person_id=pid, distinct_ids=dids))
        return person_pb2.GetDistinctIdsForPersonsResponse(person_distinct_ids=results)

    def check_cohort_membership(
        self, request: cohort_pb2.CheckCohortMembershipRequest
    ) -> cohort_pb2.CohortMembershipResponse:
        self.calls.append(_Call("check_cohort_membership", request))
        all_memberships = self._cohort_memberships.get(request.person_id, [])
        filtered = [m for m in all_memberships if m.cohort_id in request.cohort_ids]
        return cohort_pb2.CohortMembershipResponse(memberships=filtered)

    def count_cohort_members(
        self, request: cohort_pb2.CountCohortMembersRequest
    ) -> cohort_pb2.CountCohortMembersResponse:
        self.calls.append(_Call("count_cohort_members", request))
        cohort_ids_set = set(request.cohort_ids)
        count = sum(1 for (cid, _) in self._cohort_members if cid in cohort_ids_set)
        return cohort_pb2.CountCohortMembersResponse(count=count)

    def delete_cohort_member(
        self, request: cohort_pb2.DeleteCohortMemberRequest, timeout: float | None = None
    ) -> cohort_pb2.DeleteCohortMemberResponse:
        self.calls.append(_Call("delete_cohort_member", request))
        key = (request.cohort_id, request.person_id)
        deleted = key in self._cohort_members
        if deleted:
            del self._cohort_members[key]
            memberships = self._cohort_memberships.get(request.person_id, [])
            self._cohort_memberships[request.person_id] = [m for m in memberships if m.cohort_id != request.cohort_id]
        return cohort_pb2.DeleteCohortMemberResponse(deleted=deleted)

    def delete_cohort_members_bulk(
        self, request: cohort_pb2.DeleteCohortMembersBulkRequest, timeout: float | None = None
    ) -> cohort_pb2.DeleteCohortMembersBulkResponse:
        self.calls.append(_Call("delete_cohort_members_bulk", request))
        cohort_ids_set = set(request.cohort_ids)
        batch_size = request.batch_size if request.batch_size > 0 else 10000
        to_remove = [k for k in self._cohort_members if k[0] in cohort_ids_set][:batch_size]
        for key in to_remove:
            del self._cohort_members[key]
        for pid in list(self._cohort_memberships.keys()):
            self._cohort_memberships[pid] = [
                m
                for m in self._cohort_memberships[pid]
                if m.cohort_id not in cohort_ids_set or (m.cohort_id, pid) in self._cohort_members
            ]
        return cohort_pb2.DeleteCohortMembersBulkResponse(deleted_count=len(to_remove))

    def insert_cohort_members(
        self, request: cohort_pb2.InsertCohortMembersRequest, timeout: float | None = None
    ) -> cohort_pb2.InsertCohortMembersResponse:
        self.calls.append(_Call("insert_cohort_members", request))
        inserted = 0
        for pid in request.person_ids:
            key = (request.cohort_id, pid)
            if key not in self._cohort_members:
                self._cohort_members[key] = True
                self._cohort_memberships.setdefault(pid, []).append(
                    cohort_pb2.CohortMembership(cohort_id=request.cohort_id, is_member=True)
                )
                inserted += 1
        return cohort_pb2.InsertCohortMembersResponse(inserted_count=inserted)

    def list_cohort_member_ids(
        self, request: cohort_pb2.ListCohortMemberIdsRequest
    ) -> cohort_pb2.ListCohortMemberIdsResponse:
        self.calls.append(_Call("list_cohort_member_ids", request))
        all_pids = sorted(pid for (cid, pid) in self._cohort_members if cid == request.cohort_id)
        if request.cursor > 0:
            all_pids = [p for p in all_pids if p > request.cursor]
        limit = request.limit if request.limit > 0 else 10000
        has_more = len(all_pids) > limit
        page = all_pids[:limit]
        next_cursor = page[-1] if has_more else 0
        return cohort_pb2.ListCohortMemberIdsResponse(person_ids=page, next_cursor=next_cursor)

    def get_group(self, request: group_pb2.GetGroupRequest) -> group_pb2.GetGroupResponse:
        self.calls.append(_Call("get_group", request))
        group = self._groups.get((request.team_id, request.group_type_index, request.group_key))
        return group_pb2.GetGroupResponse(group=group)

    def get_groups(self, request: group_pb2.GetGroupsRequest) -> group_pb2.GroupsResponse:
        self.calls.append(_Call("get_groups", request))
        found = []
        missing = []
        for gi in request.group_identifiers:
            group = self._groups.get((request.team_id, gi.group_type_index, gi.group_key))
            if group:
                found.append(group)
            else:
                missing.append(gi)
        return group_pb2.GroupsResponse(groups=found, missing_groups=missing)

    def list_groups(self, request: group_pb2.ListGroupsRequest) -> group_pb2.ListGroupsResponse:
        self.calls.append(_Call("list_groups", request))
        all_groups = [
            g
            for (team_id, gti, _key), g in self._groups.items()
            if team_id == request.team_id and gti == request.group_type_index
        ]
        if request.group_key_contains:
            pattern = request.group_key_contains.lower()
            all_groups = [g for g in all_groups if pattern in g.group_key.lower()]
        if request.search:
            search_lower = request.search.lower()
            all_groups = [
                g
                for g in all_groups
                if search_lower in g.group_properties.decode().lower() or g.group_key == request.search
            ]
        all_groups.sort(key=lambda g: (-g.created_at, -g.id))
        if request.cursor_created_at_ms > 0:
            all_groups = [
                g for g in all_groups if (g.created_at, g.id) < (request.cursor_created_at_ms, request.cursor_id)
            ]
        limit = request.limit if request.limit > 0 else 100
        has_more = len(all_groups) > limit
        page = all_groups[:limit]
        return group_pb2.ListGroupsResponse(groups=page, has_more=has_more)

    def get_groups_batch(self, request: group_pb2.GetGroupsBatchRequest) -> group_pb2.GetGroupsBatchResponse:
        self.calls.append(_Call("get_groups_batch", request))
        results = []
        for key in request.keys:
            group = self._groups.get((key.team_id, key.group_type_index, key.group_key))
            if group:
                results.append(group_pb2.GroupWithKey(key=key, group=group))
        return group_pb2.GetGroupsBatchResponse(results=results)

    def get_group_type_mappings_by_team_id(
        self, request: group_pb2.GetGroupTypeMappingsByTeamIdRequest
    ) -> group_pb2.GroupTypeMappingsResponse:
        self.calls.append(_Call("get_group_type_mappings_by_team_id", request))
        mappings = self._group_type_mappings_by_team.get(request.team_id, [])
        return group_pb2.GroupTypeMappingsResponse(mappings=mappings)

    def get_group_type_mappings_by_team_ids(
        self, request: group_pb2.GetGroupTypeMappingsByTeamIdsRequest
    ) -> group_pb2.GroupTypeMappingsBatchResponse:
        self.calls.append(_Call("get_group_type_mappings_by_team_ids", request))
        results = []
        for tid in request.team_ids:
            mappings = self._group_type_mappings_by_team.get(tid, [])
            results.append(group_pb2.GroupTypeMappingsByKey(key=tid, mappings=mappings))
        return group_pb2.GroupTypeMappingsBatchResponse(results=results)

    def get_group_type_mappings_by_project_id(
        self, request: group_pb2.GetGroupTypeMappingsByProjectIdRequest
    ) -> group_pb2.GroupTypeMappingsResponse:
        self.calls.append(_Call("get_group_type_mappings_by_project_id", request))
        mappings = self._group_type_mappings_by_project.get(request.project_id, [])
        return group_pb2.GroupTypeMappingsResponse(mappings=mappings)

    def get_group_type_mappings_by_project_ids(
        self, request: group_pb2.GetGroupTypeMappingsByProjectIdsRequest
    ) -> group_pb2.GroupTypeMappingsBatchResponse:
        self.calls.append(_Call("get_group_type_mappings_by_project_ids", request))
        results = []
        for pid in request.project_ids:
            mappings = self._group_type_mappings_by_project.get(pid, [])
            results.append(group_pb2.GroupTypeMappingsByKey(key=pid, mappings=mappings))
        return group_pb2.GroupTypeMappingsBatchResponse(results=results)

    # ── Group writes ─────────────────────────────────────────────────

    def create_group(self, request: group_pb2.CreateGroupRequest) -> group_pb2.CreateGroupResponse:
        self.calls.append(_Call("create_group", request))
        key = (request.team_id, request.group_type_index, request.group_key)
        existing = self._groups.get(key)
        if existing is not None:
            return group_pb2.CreateGroupResponse(group=existing)
        next_id = max((g.id for g in self._groups.values()), default=0) + 1
        group = group_pb2.Group(
            id=next_id,
            team_id=request.team_id,
            group_type_index=request.group_type_index,
            group_key=request.group_key,
            group_properties=request.group_properties,
            created_at=request.created_at,
            version=0,
        )
        self._groups[key] = group
        response = group_pb2.CreateGroupResponse(group=group)
        return response

    def update_group(self, request: group_pb2.UpdateGroupRequest) -> group_pb2.UpdateGroupResponse:
        self.calls.append(_Call("update_group", request))
        key = (request.team_id, request.group_type_index, request.group_key)
        group = self._groups.get(key)
        if group is None:
            import grpc

            raise grpc.RpcError()
        for field in request.update_mask:
            if field == "group_properties":
                group.group_properties = request.group_properties
            elif field == "properties_last_updated_at":
                group.properties_last_updated_at = request.properties_last_updated_at
            elif field == "properties_last_operation":
                group.properties_last_operation = request.properties_last_operation
            elif field == "created_at":
                group.created_at = request.created_at
        group.version += 1
        self._groups[key] = group
        return group_pb2.UpdateGroupResponse(group=group, updated=True)

    def delete_groups_batch_for_team(
        self, request: group_pb2.DeleteGroupsBatchForTeamRequest, timeout: float | None = None
    ) -> group_pb2.DeleteGroupsBatchForTeamResponse:
        self.calls.append(_Call("delete_groups_batch_for_team", request))
        to_delete = [k for k in self._groups if k[0] == request.team_id][: request.batch_size]
        for key in to_delete:
            del self._groups[key]
        return group_pb2.DeleteGroupsBatchForTeamResponse(deleted_count=len(to_delete))

    # ── Group type mapping writes ───────────────────────────────────

    def get_group_type_mapping_by_dashboard_id(
        self, request: group_pb2.GetGroupTypeMappingByDashboardIdRequest
    ) -> group_pb2.GetGroupTypeMappingByDashboardIdResponse:
        self.calls.append(_Call("get_group_type_mapping_by_dashboard_id", request))
        for mappings in self._group_type_mappings_by_project.values():
            for m in mappings:
                if m.detail_dashboard_id == request.dashboard_id and m.team_id == request.team_id:
                    return group_pb2.GetGroupTypeMappingByDashboardIdResponse(mapping=m)
        return group_pb2.GetGroupTypeMappingByDashboardIdResponse()

    def count_group_type_mappings(
        self, request: group_pb2.CountGroupTypeMappingsRequest
    ) -> group_pb2.CountGroupTypeMappingsResponse:
        self.calls.append(_Call("count_group_type_mappings", request))
        counts = []
        for team_id, team_mappings in self._group_type_mappings_by_team.items():
            if team_mappings:
                counts.append(group_pb2.GroupTypeMappingCount(team_id=team_id, count=len(team_mappings)))
        counts.sort(key=lambda c: c.team_id)
        return group_pb2.CountGroupTypeMappingsResponse(counts=counts)

    def update_group_type_mapping(
        self, request: group_pb2.UpdateGroupTypeMappingRequest
    ) -> group_pb2.UpdateGroupTypeMappingResponse:
        self.calls.append(_Call("update_group_type_mapping", request))
        mappings = self._group_type_mappings_by_project.get(request.project_id, [])
        for m in mappings:
            if m.group_type_index == request.group_type_index:
                for field in request.update_mask:
                    if field == "name_singular":
                        m.name_singular = request.name_singular
                    elif field == "name_plural":
                        m.name_plural = request.name_plural
                    elif field == "detail_dashboard_id":
                        m.detail_dashboard_id = request.detail_dashboard_id
                    elif field == "default_columns":
                        m.default_columns = request.default_columns
                    elif field == "created_at":
                        # Mirror the replica: the path in the mask with no value nulls the column.
                        if request.HasField("created_at"):
                            m.created_at = request.created_at
                        else:
                            m.ClearField("created_at")
                return group_pb2.UpdateGroupTypeMappingResponse(mapping=m)
        import grpc

        raise grpc.RpcError()

    def delete_group_type_mapping(
        self, request: group_pb2.DeleteGroupTypeMappingRequest
    ) -> group_pb2.DeleteGroupTypeMappingResponse:
        self.calls.append(_Call("delete_group_type_mapping", request))
        mappings = self._group_type_mappings_by_project.get(request.project_id, [])
        original_len = len(mappings)
        self._group_type_mappings_by_project[request.project_id] = [
            m for m in mappings if m.group_type_index != request.group_type_index
        ]
        deleted = len(self._group_type_mappings_by_project[request.project_id]) < original_len
        for tid in list(self._group_type_mappings_by_team):
            self._group_type_mappings_by_team[tid] = [
                m
                for m in self._group_type_mappings_by_team[tid]
                if not (m.project_id == request.project_id and m.group_type_index == request.group_type_index)
            ]
        return group_pb2.DeleteGroupTypeMappingResponse(deleted=deleted)

    def delete_group_type_mappings_batch_for_team(
        self, request: group_pb2.DeleteGroupTypeMappingsBatchForTeamRequest, timeout: float | None = None
    ) -> group_pb2.DeleteGroupTypeMappingsBatchForTeamResponse:
        self.calls.append(_Call("delete_group_type_mappings_batch_for_team", request))
        deleted = 0
        for pid in list(self._group_type_mappings_by_project):
            before = len(self._group_type_mappings_by_project[pid])
            self._group_type_mappings_by_project[pid] = [
                m for m in self._group_type_mappings_by_project[pid] if m.team_id != request.team_id
            ]
            deleted += before - len(self._group_type_mappings_by_project[pid])
            if deleted >= request.batch_size:
                break
        return group_pb2.DeleteGroupTypeMappingsBatchForTeamResponse(deleted_count=deleted)

    # ── Feature flag hash key overrides ───────────────────────────────

    def delete_hash_key_overrides_by_teams(
        self, request: feature_flag_pb2.DeleteHashKeyOverridesByTeamsRequest, timeout: float | None = None
    ) -> feature_flag_pb2.DeleteHashKeyOverridesByTeamsResponse:
        # The fake does not track hash key overrides; record the call and report nothing deleted.
        self.calls.append(_Call("delete_hash_key_overrides_by_teams", request))
        return feature_flag_pb2.DeleteHashKeyOverridesByTeamsResponse(deleted_count=0)

    # ── Person deletes ────────────────────────────────────────────────

    def _remove_person(self, team_id: int, person: person_pb2.Person) -> None:
        self._persons_by_uuid.pop((team_id, person.uuid), None)
        self._persons_by_id.pop((team_id, person.id), None)
        for did in self._distinct_ids.pop((team_id, person.id), []):
            self._persons_by_distinct_id.pop((team_id, did.distinct_id), None)
            self._tombstoned_distinct_ids.discard((team_id, did.distinct_id))
        self._cohort_memberships.pop(person.id, None)
        for key in [key for key in self._cohort_members if key[1] == person.id]:
            del self._cohort_members[key]

    def delete_persons(
        self, request: person_pb2.DeletePersonsRequest, timeout: float | None = None
    ) -> person_pb2.DeletePersonsResponse:
        self.calls.append(_Call("delete_persons", request))
        if request.mode == person_pb2.DELETE_PERSONS_MODE_HARD:
            raise ValueError("DELETE_PERSONS_MODE_HARD is not supported")
        if request.mode not in (person_pb2.DELETE_PERSONS_MODE_UNSPECIFIED, person_pb2.DELETE_PERSONS_MODE_TOMBSTONE):
            raise ValueError(f"Unknown DeletePersonsMode {request.mode}")
        response = person_pb2.DeletePersonsResponse(tombstoned=True)
        for uuid in request.person_uuids:
            person = self._persons_by_uuid.get((request.team_id, uuid))
            if person is None:
                continue
            tombstoned = response.tombstones.add(person_uuid=person.uuid)
            if person.is_deleted:
                # Mirrors the server: an already tombstoned row is reported with the versions it
                # holds and not counted, so a retry can publish the same ClickHouse tombstones.
                tombstoned.version = person.version
                for did in sorted(
                    self._distinct_ids.get((request.team_id, person.id), []), key=lambda d: d.distinct_id
                ):
                    if (request.team_id, did.distinct_id) in self._tombstoned_distinct_ids:
                        tombstoned.distinct_ids.add(distinct_id=did.distinct_id, version=did.version)
                continue
            response.deleted_count += 1
            tombstoned.version = self._tombstone_person(request.team_id, person, tombstoned)
            self.tombstone_queue[(request.team_id, str(person.uuid))] = tombstoned.version
            self.tombstone_queued_at_ms.setdefault((request.team_id, str(person.uuid)), int(time.time() * 1000))
        response.tombstones.sort(key=lambda t: t.person_uuid)
        return response

    def _tombstone_person(
        self, team_id: int, person: person_pb2.Person, tombstoned: person_pb2.TombstonedPerson
    ) -> int:
        """Tombstone a person and its distinct ids the way the replica does, reporting the versions."""
        version = person.version + 1
        person.is_deleted = True
        person.version = version
        person.properties = b"{}"
        for did in sorted(self._distinct_ids.get((team_id, person.id), []), key=lambda d: d.distinct_id):
            if (team_id, did.distinct_id) in self._tombstoned_distinct_ids:
                continue
            did.version = did.version + 1
            self._tombstoned_distinct_ids.add((team_id, did.distinct_id))
            tombstoned.distinct_ids.add(distinct_id=did.distinct_id, version=did.version)
        return version

    # ── Lifecycle sagas ───────────────────────────────────────────────

    def _lifecycle_delete_persons(
        self, request: lifecycle_pb2.DeletePersonsRequest, timeout: float | None = None
    ) -> lifecycle_pb2.DeletePersonsResponse:
        self.calls.append(_Call("lifecycle.delete_persons", request, timeout=timeout))
        self._validate_lifecycle_delete(request)

        frozen = (request.team_id, tuple(request.person_ids))
        recorded = self._lifecycle_ops.get(request.op_id)
        if recorded is not None:
            team_id, person_ids, response = recorded
            if (team_id, person_ids) != frozen:
                raise _FakeRpcError(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    f"op {request.op_id} already exists with a different request",
                    ((SEMANTIC_REFUSAL_METADATA_KEY, "op_id_reused"),),
                )
            copy = lifecycle_pb2.DeletePersonsResponse()
            copy.CopyFrom(response)
            return copy

        # One decision per distinct person, so a duplicated id reports the same outcome twice.
        outcomes: dict[int, lifecycle_pb2.DeletePersonOutcome] = {}
        versions: dict[int, int] = {}
        for person_id in request.person_ids:
            if person_id in outcomes:
                continue
            person = self._live(self._persons_by_id.get((request.team_id, person_id)))
            if person is None:
                outcomes[person_id] = lifecycle_pb2.DELETE_PERSON_OUTCOME_NOT_FOUND
            elif (request.team_id, person_id) in self._lifecycle_marks:
                outcomes[person_id] = lifecycle_pb2.DELETE_PERSON_OUTCOME_SKIPPED_CONFLICT
            else:
                # No publish-queue row: the death document and the outbox carry the ClickHouse tombstones.
                versions[person_id] = self._tombstone_person(request.team_id, person, person_pb2.TombstonedPerson())
                self._cohort_memberships.pop(person.id, None)
                for key in [key for key in self._cohort_members if key[1] == person.id]:
                    del self._cohort_members[key]
                outcomes[person_id] = lifecycle_pb2.DELETE_PERSON_OUTCOME_DELETED

        response = lifecycle_pb2.DeletePersonsResponse(op_id=request.op_id)
        for person_id in request.person_ids:
            result = response.results.add(person_id=person_id, outcome=outcomes[person_id])
            if person_id in versions and (request.team_id, person_id) not in self._lifecycle_versionless:
                result.person_version = versions[person_id]
        self._lifecycle_ops[request.op_id] = (frozen[0], frozen[1], response)
        copy = lifecycle_pb2.DeletePersonsResponse()
        copy.CopyFrom(response)
        return copy

    @staticmethod
    def _validate_lifecycle_delete(request: lifecycle_pb2.DeletePersonsRequest) -> None:
        """Mirror the identity server's request validation (rust/personhog-identity, validation.rs)."""
        if not 0 < request.team_id <= _MAX_TEAM_ID:
            reason = "team_id must be a positive 32-bit integer"
        elif not request.person_ids:
            reason = "person_ids must not be empty"
        elif len(request.person_ids) > LIFECYCLE_DELETE_MAX_PERSON_IDS:
            reason = f"batch size {len(request.person_ids)} exceeds maximum {LIFECYCLE_DELETE_MAX_PERSON_IDS}"
        elif any(person_id <= 0 for person_id in request.person_ids):
            reason = "person_ids must be positive integers"
        else:
            try:
                UUID(request.op_id)
            except ValueError:
                reason = "op_id must be a valid UUID"
            else:
                return
        raise _FakeRpcError(grpc.StatusCode.INVALID_ARGUMENT, reason)

    def ack_person_tombstones(
        self, request: person_pb2.AckPersonTombstonesRequest, timeout: float | None = None
    ) -> person_pb2.AckPersonTombstonesResponse:
        self.calls.append(_Call("ack_person_tombstones", request))
        cleared = 0
        for acked in request.tombstones:
            key = (request.team_id, acked.person_uuid)
            if key in self.tombstone_queue and self.tombstone_queue[key] <= acked.version:
                del self.tombstone_queue[key]
                self.tombstone_queued_at_ms.pop(key, None)
                cleared += 1
        return person_pb2.AckPersonTombstonesResponse(cleared_count=cleared)

    def list_person_tombstone_queue(
        self, request: person_pb2.ListPersonTombstoneQueueRequest, timeout: float | None = None
    ) -> person_pb2.ListPersonTombstoneQueueResponse:
        self.calls.append(_Call("list_person_tombstone_queue", request))
        after = (request.after_team_id, request.after_person_uuid)
        keys = sorted(
            key
            for key in self.tombstone_queue
            if key > after and (not request.HasField("team_id") or key[0] == request.team_id)
        )
        response = person_pb2.ListPersonTombstoneQueueResponse()
        for team_id, person_uuid in keys[: request.limit or 1000]:
            response.entries.add(
                team_id=team_id,
                person_uuid=person_uuid,
                person_version=self.tombstone_queue[(team_id, person_uuid)],
                tombstoned_at=self.tombstone_queued_at_ms.get((team_id, person_uuid), 0),
            )
        return response

    def get_person_tombstones(
        self, request: person_pb2.GetPersonTombstonesRequest, timeout: float | None = None
    ) -> person_pb2.GetPersonTombstonesResponse:
        self.calls.append(_Call("get_person_tombstones", request))
        response = person_pb2.GetPersonTombstonesResponse()
        for uuid in request.person_uuids:
            person = self._persons_by_uuid.get((request.team_id, uuid))
            if person is None or not person.is_deleted:
                continue
            tombstoned = response.tombstones.add(person_uuid=person.uuid, version=person.version)
            for did in sorted(self._distinct_ids.get((request.team_id, person.id), []), key=lambda d: d.distinct_id):
                if (request.team_id, did.distinct_id) in self._tombstoned_distinct_ids:
                    tombstoned.distinct_ids.add(distinct_id=did.distinct_id, version=did.version)
        response.tombstones.sort(key=lambda t: t.person_uuid)
        return response

    def delete_tombstoned_persons(
        self, request: person_pb2.DeleteTombstonedPersonsRequest, timeout: float | None = None
    ) -> person_pb2.DeleteTombstonedPersonsResponse:
        # Mirrors the server, in person id order: a tombstoned person whose distinct ids fit the
        # leftover budget goes whole unless one is live (blocked); the first that does not fit
        # gives up as many as the leftover allows and stays pending; the rest stay pending untouched.
        if request.person_uuids and request.bounded_persons:
            raise ValueError("Set either person_uuids or bounded_persons, not both")
        response = person_pb2.DeleteTombstonedPersonsResponse(version_guard_applied=bool(request.bounded_persons))
        budget = max(1, min(request.max_rows or DELETE_TOMBSTONED_DEFAULT_ROWS, self.tombstoned_delete_max_rows))
        bounds: dict[str, int] = {}
        for bounded in request.bounded_persons:
            if bounded.max_version < 0:
                raise ValueError("max_version must not be negative")
            bounds[bounded.person_uuid] = min(bounds.get(bounded.person_uuid, bounded.max_version), bounded.max_version)
        candidates: list[tuple[str, person_pb2.Person]] = []
        for uuid in dict.fromkeys([*request.person_uuids, *bounds]):
            person = self._persons_by_uuid.get((request.team_id, uuid))
            if person is None:
                continue
            if not person.is_deleted:
                response.skipped_live_count += 1
                continue
            if request.bounded_persons and person.version > bounds[uuid]:
                response.skipped_version_count += 1
                continue
            candidates.append((uuid, person))
        candidates.sort(key=lambda candidate: candidate[1].id)

        trim: tuple[str, person_pb2.Person] | None = None
        for uuid, person in candidates:
            dids = self._distinct_ids.get((request.team_id, person.id), [])
            if len(dids) > budget:
                trim = trim or (uuid, person)
                response.pending_person_uuids.append(uuid)
                continue
            budget -= len(dids)
            if any((request.team_id, did.distinct_id) not in self._tombstoned_distinct_ids for did in dids):
                response.blocked_person_uuids.append(uuid)
                continue
            self._remove_person(request.team_id, person)
            response.deleted_count += 1
            response.rows_deleted += len(dids)

        if trim is not None:
            uuid, person = trim
            dids = self._distinct_ids.get((request.team_id, person.id), [])
            step = dids[:budget]
            if any((request.team_id, did.distinct_id) not in self._tombstoned_distinct_ids for did in step):
                response.pending_person_uuids.remove(uuid)
                response.blocked_person_uuids.append(uuid)
            else:
                for did in step:
                    dids.remove(did)
                    self._persons_by_distinct_id.pop((request.team_id, did.distinct_id), None)
                    self._tombstoned_distinct_ids.discard((request.team_id, did.distinct_id))
                response.rows_deleted += len(step)
        self.calls.append(_Call("delete_tombstoned_persons", request, response))
        return response

    def delete_persons_batch_for_team(
        self, request: person_pb2.DeletePersonsBatchForTeamRequest, timeout: float | None = None
    ) -> person_pb2.DeletePersonsBatchForTeamResponse:
        deleted_count = 0
        # Find up to batch_size persons for this team
        to_delete = []
        for (team_id, uuid), person in list(self._persons_by_uuid.items()):
            if team_id == request.team_id:
                to_delete.append((team_id, uuid, person))
                if len(to_delete) >= request.batch_size:
                    break
        for team_id, _uuid, person in to_delete:
            self._remove_person(team_id, person)
            deleted_count += 1
        response = person_pb2.DeletePersonsBatchForTeamResponse(deleted_count=deleted_count)
        self.calls.append(_Call("delete_persons_batch_for_team", request, response))
        return response

    # ── Person split ──────────────────────────────────────────────────

    def split_person(
        self, request: person_pb2.SplitPersonRequest, timeout: float | None = None
    ) -> person_pb2.SplitPersonResponse:
        """Stateful mirror of the real RPC: validates ownership, creates new
        persons with deterministic UUIDv5s (a random UUID when a live person
        holds it; a tombstone there is revived with its created_at), moves the
        distinct_ids, and bumps versions by 101. Results are returned in
        request order, like the real service.
        """
        self.calls.append(_Call("split_person", request))

        key = (request.team_id, request.person_id)
        source = self._persons_by_id.get(key)
        if source is None:
            raise KeyError(f"person_id={request.person_id} not found (team_id={request.team_id})")

        mappings = self._distinct_ids.get(key, [])
        mapping_by_did = {m.distinct_id: m for m in mappings}
        unknown = [did for did in request.distinct_ids_to_split if did not in mapping_by_did]
        if unknown:
            raise KeyError(
                f"distinct_ids {unknown} do not belong to person_id={request.person_id} (team_id={request.team_id})"
            )

        new_person_version = source.version + 101
        splits: list[person_pb2.SplitResult] = []
        for did in request.distinct_ids_to_split:
            new_uuid = str(uuidFromDistinctId(request.team_id, did))

            existing = self._persons_by_uuid.get((request.team_id, new_uuid))
            if existing is not None and not existing.is_deleted:
                new_uuid = str(uuid4())
                existing = None
            if existing is not None:
                existing.is_deleted = False
                existing.version = max(existing.version + 1, new_person_version)
                new_person = existing
            else:
                self._next_split_person_id += 1
                new_person = self.add_person(
                    team_id=request.team_id,
                    person_id=self._next_split_person_id,
                    uuid=new_uuid,
                    version=new_person_version,
                    created_at=int(time.time() * 1000),
                )

            pdi_version = (mapping_by_did[did].version or 0) + 101
            mappings.remove(mapping_by_did[did])
            target_mappings = self._distinct_ids.setdefault((request.team_id, new_person.id), [])
            target_mappings[:] = [m for m in target_mappings if m.distinct_id != did]
            target_mappings.append(person_pb2.DistinctIdWithVersion(distinct_id=did, version=pdi_version))
            self._persons_by_distinct_id[(request.team_id, did)] = new_person

            splits.append(
                person_pb2.SplitResult(
                    distinct_id=did,
                    new_person_uuid=new_uuid,
                    new_person_version=new_person.version,
                    pdi_version=pdi_version,
                    new_person_created_at_ms=new_person.created_at,
                )
            )

        return person_pb2.SplitPersonResponse(splits=splits)

    # ── Undelete repair ───────────────────────────────────────────────

    def set_person_distinct_id_version_floor(
        self, request: person_pb2.SetPersonDistinctIdVersionFloorRequest, timeout: float | None = None
    ) -> person_pb2.SetPersonDistinctIdVersionFloorResponse:
        self.calls.append(_Call("set_person_distinct_id_version_floor", request))

        person = self._persons_by_distinct_id.get((request.team_id, request.distinct_id))
        if person is None:
            return person_pb2.SetPersonDistinctIdVersionFloorResponse()

        # Guarded bump: never lower the stored version. The person is returned whenever
        # the distinct_id exists, even if the version is left unchanged.
        for mapping in self._distinct_ids.get((request.team_id, person.id), []):
            if mapping.distinct_id == request.distinct_id and mapping.version < request.min_version:
                mapping.version = request.min_version
        return person_pb2.SetPersonDistinctIdVersionFloorResponse(person=person)

    def set_person_version_floor(
        self, request: person_pb2.SetPersonVersionFloorRequest, timeout: float | None = None
    ) -> person_pb2.SetPersonVersionFloorResponse:
        self.calls.append(_Call("set_person_version_floor", request))

        person = self._persons_by_id.get((request.team_id, request.person_id))
        if person is None or person.version >= request.min_version:
            return person_pb2.SetPersonVersionFloorResponse(updated=False)

        person.version = request.min_version
        return person_pb2.SetPersonVersionFloorResponse(updated=True)

    # ── Version floors ─────

    @staticmethod
    def _check_version_rpc_batch(keys: list[str]) -> None:
        """Mirror the server's INVALID_ARGUMENT checks."""
        if len(keys) > VERSION_RPC_MAX_KEYS:
            raise ValueError(f"Maximum {VERSION_RPC_MAX_KEYS} keys per request")
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate key in request")

    def _insert_person_tombstone(self, team_id: int, uuid: str, version: int) -> person_pb2.Person:
        self._next_split_person_id += 1
        return self.add_person(
            team_id=team_id,
            person_id=self._next_split_person_id,
            uuid=uuid,
            version=version,
            is_deleted=True,
            created_at=int(time.time() * 1000),
        )

    @staticmethod
    def _floor_outcome(is_deleted: bool, version: int, min_version: int) -> person_pb2.VersionFloorOutcome:
        if not is_deleted:
            return person_pb2.VERSION_FLOOR_OUTCOME_LIVE
        if version < min_version:
            return person_pb2.VERSION_FLOOR_OUTCOME_TOMBSTONE_RAISED
        return person_pb2.VERSION_FLOOR_OUTCOME_TOMBSTONE_AT_FLOOR

    def ensure_person_version_floors(
        self, request: person_pb2.EnsurePersonVersionFloorsRequest, timeout: float | None = None
    ) -> person_pb2.EnsurePersonVersionFloorsResponse:
        self.calls.append(_Call("ensure_person_version_floors", request))
        self._check_version_rpc_batch([f.person_uuid for f in request.floors])
        if any(f.min_version < 0 for f in request.floors):
            raise ValueError("min_version must not be negative")
        response = person_pb2.EnsurePersonVersionFloorsResponse()
        for floor in request.floors:
            person = self._persons_by_uuid.get((request.team_id, floor.person_uuid))
            if person is None:
                self._insert_person_tombstone(request.team_id, floor.person_uuid, floor.min_version)
                response.results.add(
                    person_uuid=floor.person_uuid,
                    outcome=person_pb2.VERSION_FLOOR_OUTCOME_TOMBSTONE_INSERTED,
                    version=floor.min_version,
                )
                continue
            outcome = self._floor_outcome(person.is_deleted, person.version, floor.min_version)
            if person.is_deleted:
                person.version = max(person.version, floor.min_version)
            response.results.add(person_uuid=floor.person_uuid, outcome=outcome, version=person.version)
        return response

    # ── Consistency scan reads ───────────────────────────────────────

    def get_distinct_id_rows(
        self, request: person_pb2.GetDistinctIdRowsRequest, timeout: float | None = None
    ) -> person_pb2.GetDistinctIdRowsResponse:
        """Mapping rows, live or tombstoned, for mappings the fake tracks per person."""
        self.calls.append(_Call("get_distinct_id_rows", request))
        if len(request.distinct_ids) > 1000:
            raise ValueError("Maximum 1000 distinct ids per request")
        wanted = set(request.distinct_ids)
        response = person_pb2.GetDistinctIdRowsResponse()
        rows = []
        for (team_id, person_id), mappings in self._distinct_ids.items():
            if team_id != request.team_id:
                continue
            person = self._persons_by_id.get((team_id, person_id))
            for mapping in mappings:
                if mapping.distinct_id not in wanted:
                    continue
                row = person_pb2.DistinctIdRow(
                    distinct_id=mapping.distinct_id,
                    person_id=person_id,
                    version=mapping.version or 0,
                    is_deleted=(team_id, mapping.distinct_id) in self._tombstoned_distinct_ids,
                )
                if person is not None:
                    row.person_uuid = person.uuid
                    row.person_is_deleted = person.is_deleted
                rows.append(row)
        response.rows.extend(sorted(rows, key=lambda r: r.distinct_id))
        return response

    def list_persons_for_team(
        self, request: person_pb2.ListPersonsForTeamRequest, timeout: float | None = None
    ) -> person_pb2.ListPersonsForTeamResponse:
        self.calls.append(_Call("list_persons_for_team", request))
        limit = request.limit or 1000
        if not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000")
        persons = sorted(
            (
                p
                for (team_id, person_id), p in self._persons_by_id.items()
                if team_id == request.team_id
                and person_id > request.after_person_id
                and (not request.HasField("before_person_id") or person_id < request.before_person_id)
            ),
            key=lambda p: p.id,
        )[:limit]
        response = person_pb2.ListPersonsForTeamResponse()
        for person in persons:
            response.persons.add(
                id=person.id,
                uuid=person.uuid,
                version=person.version,
                is_deleted=person.is_deleted,
                has_live_distinct_ids=any(
                    (request.team_id, d.distinct_id) not in self._tombstoned_distinct_ids
                    for d in self._distinct_ids.get((request.team_id, person.id), [])
                ),
                created_at_ms=person.created_at,
            )
        if len(persons) == limit:
            response.next_after_person_id = persons[-1].id
        return response

    # ── Consistency repair writes ────────────────────────────────────
    # Mirror the replica's outcomes; the fake has no lifecycle marks or row locks.

    def _check_repair_batch(self, keys: list[str], versions: list[int], *, uuid_keys: bool) -> None:
        """Mirror the server's INVALID_ARGUMENT checks, which reject the whole request before any write."""
        self._check_version_rpc_batch(keys)
        if any(v < 0 for v in versions):
            raise ValueError("versions must not be negative")
        if uuid_keys:
            parsed = [UUID(k) for k in keys]
            if len(set(parsed)) != len(parsed):
                raise ValueError("Duplicate key in request")

    def raise_person_version_floors(
        self, request: person_pb2.RaisePersonVersionFloorsRequest, timeout: float | None = None
    ) -> person_pb2.RaisePersonVersionFloorsResponse:
        self.calls.append(_Call("raise_person_version_floors", request))
        self._check_repair_batch(
            [f.person_uuid for f in request.floors], [f.min_version for f in request.floors], uuid_keys=True
        )
        response = person_pb2.RaisePersonVersionFloorsResponse()
        for floor in request.floors:
            person = self._persons_by_uuid.get((request.team_id, floor.person_uuid))
            if person is None:
                outcome, version = person_pb2.RAISE_OUTCOME_MISSING, 0
            elif person.is_deleted:
                outcome, version = person_pb2.RAISE_OUTCOME_NOT_LIVE, person.version
            elif person.version >= floor.min_version:
                outcome, version = person_pb2.RAISE_OUTCOME_AT_OR_ABOVE, person.version
            else:
                person.version = floor.min_version
                outcome, version = person_pb2.RAISE_OUTCOME_RAISED, person.version
            response.results.add(person_uuid=floor.person_uuid, outcome=outcome, version=version)
        return response

    def raise_person_version(
        self, request: person_pb2.RaisePersonVersionRequest, timeout: float | None = None
    ) -> person_pb2.RaisePersonVersionResponse:
        self.calls.append(_Call("raise_person_version", request))
        person = self._live(self._persons_by_id.get((request.team_id, request.person_id)))
        if person is None:
            import grpc

            error = grpc.RpcError()
            error.code = lambda: grpc.StatusCode.NOT_FOUND
            raise error
        # The stored row stays as it is, because Postgres trails the leader until its writer applies the raise.
        written = person_pb2.Person()
        written.CopyFrom(person)
        raised = person.version < request.min_version
        if raised:
            written.version = request.min_version
        return person_pb2.RaisePersonVersionResponse(person=written, raised=raised)

    def restore_persons(
        self, request: person_pb2.RestorePersonsRequest, timeout: float | None = None
    ) -> person_pb2.RestorePersonsResponse:
        self.calls.append(_Call("restore_persons", request))
        self._check_repair_batch(
            [p.person_uuid for p in request.persons], [p.version for p in request.persons], uuid_keys=True
        )
        parsed_properties = [json.loads(p.properties) for p in request.persons]
        if not all(isinstance(props, dict) for props in parsed_properties):
            raise ValueError("properties must be a JSON object")
        listed = [d for p in request.persons for d in p.distinct_ids]
        if len(listed) > RESTORE_MAX_DISTINCT_IDS:
            raise ValueError(f"At most {RESTORE_MAX_DISTINCT_IDS} distinct ids per restore, got {len(listed)}")
        if len({d.distinct_id for d in listed}) != len(listed) or any(
            not d.distinct_id or d.version < 0 for d in listed
        ):
            raise ValueError("distinct_ids must be unique, non-empty and at non-negative versions")
        response = person_pb2.RestorePersonsResponse()
        for restored, properties in zip(request.persons, parsed_properties):
            existing = self._persons_by_uuid.get((request.team_id, restored.person_uuid))
            if existing is not None:
                outcome = (
                    person_pb2.RESTORE_OUTCOME_EXISTS_TOMBSTONED
                    if existing.is_deleted
                    else person_pb2.RESTORE_OUTCOME_EXISTS_LIVE
                )
                response.results.add(
                    person_uuid=restored.person_uuid, outcome=outcome, person_id=existing.id, version=existing.version
                )
                continue
            free = [
                d
                for d in restored.distinct_ids
                if (request.team_id, d.distinct_id) not in self._persons_by_distinct_id
                and (request.team_id, d.distinct_id) not in self._tombstoned_distinct_ids
            ]
            if restored.distinct_ids and not free:
                response.results.add(
                    person_uuid=restored.person_uuid, outcome=person_pb2.RESTORE_OUTCOME_NO_DISTINCT_ID
                )
                continue
            self._next_split_person_id += 1
            person = self.add_person(
                team_id=request.team_id,
                person_id=self._next_split_person_id,
                uuid=restored.person_uuid,
                properties=properties,
                created_at=restored.created_at_ms,
                version=restored.version,
                is_identified=restored.is_identified,
                distinct_ids=[d.distinct_id for d in free],
                distinct_id_versions={d.distinct_id: d.version for d in free},
            )
            response.results.add(
                person_uuid=restored.person_uuid,
                outcome=person_pb2.RESTORE_OUTCOME_INSERTED,
                person_id=person.id,
                version=person.version,
                restored_distinct_ids=[d.distinct_id for d in free],
            )
        return response

    def _mapping_row(self, team_id: int, distinct_id: str) -> person_pb2.DistinctIdRow | None:
        owner = self._persons_by_distinct_id.get((team_id, distinct_id))
        if owner is None:
            return None
        mapping = next(
            (m for m in self._distinct_ids.get((team_id, owner.id), []) if m.distinct_id == distinct_id), None
        )
        if mapping is None:
            return None
        return person_pb2.DistinctIdRow(
            distinct_id=distinct_id,
            person_id=owner.id,
            person_uuid=owner.uuid,
            version=mapping.version or 0,
            is_deleted=(team_id, distinct_id) in self._tombstoned_distinct_ids,
            person_is_deleted=owner.is_deleted,
        )

    def write_distinct_ids(
        self, request: person_pb2.WriteDistinctIdsRequest, timeout: float | None = None
    ) -> person_pb2.WriteDistinctIdsResponse:
        self.calls.append(_Call("write_distinct_ids", request))
        self._check_repair_batch(
            [w.distinct_id for w in request.writes], [w.min_version for w in request.writes], uuid_keys=False
        )
        for write in request.writes:
            UUID(write.person_uuid)
            if write.action not in (
                person_pb2.DISTINCT_ID_WRITE_ACTION_INSERT,
                person_pb2.DISTINCT_ID_WRITE_ACTION_RAISE,
            ):
                raise ValueError(f"Unknown action {write.action} for {write.distinct_id}")
        response = person_pb2.WriteDistinctIdsResponse()
        team_id = request.team_id
        for write in request.writes:
            outcome = self._apply_distinct_id_write(team_id, write)
            result = response.results.add(distinct_id=write.distinct_id, outcome=outcome)
            row = self._mapping_row(team_id, write.distinct_id)
            if row is not None:
                result.row.CopyFrom(row)
        return response

    def _apply_distinct_id_write(
        self, team_id: int, write: person_pb2.DistinctIdWrite
    ) -> person_pb2.DistinctIdWriteOutcome:
        person = self._persons_by_uuid.get((team_id, write.person_uuid))
        if person is None or person.is_deleted:
            return person_pb2.DISTINCT_ID_WRITE_OUTCOME_PERSON_NOT_LIVE
        row = self._mapping_row(team_id, write.distinct_id)
        exists = row is not None or (team_id, write.distinct_id) in self._tombstoned_distinct_ids
        if write.action == person_pb2.DISTINCT_ID_WRITE_ACTION_INSERT:
            if exists:
                return person_pb2.DISTINCT_ID_WRITE_OUTCOME_PRECONDITION_FAILED
            self._persons_by_distinct_id[(team_id, write.distinct_id)] = person
            self._distinct_ids.setdefault((team_id, person.id), []).append(
                person_pb2.DistinctIdWithVersion(distinct_id=write.distinct_id, version=write.min_version)
            )
            return person_pb2.DISTINCT_ID_WRITE_OUTCOME_APPLIED
        expected_ok = not write.HasField("expected_version") or (
            row is not None and row.version == write.expected_version
        )
        if row is None or row.is_deleted or row.person_id != person.id or not expected_ok:
            return person_pb2.DISTINCT_ID_WRITE_OUTCOME_PRECONDITION_FAILED
        mapping = next(m for m in self._distinct_ids[(team_id, person.id)] if m.distinct_id == write.distinct_id)
        if (mapping.version or 0) >= write.min_version:
            return person_pb2.DISTINCT_ID_WRITE_OUTCOME_UNCHANGED
        mapping.version = write.min_version
        return person_pb2.DISTINCT_ID_WRITE_OUTCOME_APPLIED

    # ── Assertion helpers ────────────────────────────────────────────

    def assert_called(self, method: str, *, times: int | None = None) -> list[_Call]:
        matched = [c for c in self.calls if c.method == method]
        if times is not None:
            assert len(matched) == times, f"Expected {method} to be called {times} time(s), got {len(matched)}"
        else:
            assert matched, f"Expected {method} to be called at least once, but it was never called"
        return matched

    def assert_not_called(self, method: str) -> None:
        matched = [c for c in self.calls if c.method == method]
        assert not matched, f"Expected {method} to not be called, but it was called {len(matched)} time(s)"


@contextmanager
def fake_personhog_client():
    """Context manager that patches the personhog client singleton.

    Yields a ``FakePersonHogClient`` that is pre-seeded as empty. personhog is
    the sole read path, so patching ``get_personhog_client`` is all that's needed.

    Example::

        with fake_personhog_client() as fake:
            fake.add_group_type_mapping(project_id=1, group_type="org", group_type_index=0)
            result = some_function_that_uses_personhog(1)
    """
    fake = FakePersonHogClient()
    with patch("posthog.personhog_client.client.get_personhog_client", return_value=fake):
        yield fake


# ── Global singleton for conftest integration ───────────────────────

_active_fake: FakePersonHogClient | None = None


def set_active_fake(fake: FakePersonHogClient | None) -> None:
    global _active_fake
    _active_fake = fake


def get_active_fake() -> FakePersonHogClient:
    assert _active_fake is not None, "get_active_fake() called outside activate_personhog_fake() context"
    return _active_fake


def personhog_fake_active() -> bool:
    """Whether a personhog fake is active for the current test.

    The test seed helpers use this to choose between seeding the fake (fake active, the default)
    and writing the real persons DB via off-Django psycopg (fake off — persons_db_direct tests).
    """
    return _active_fake is not None


@contextmanager
def activate_personhog_fake():
    """Activate a FakePersonHogClient for the duration of a test.

    Patches get_personhog_client so all reads route through the fake and blocks
    persons-DB ORM access so a stray Person.objects.* call fails loudly.  Test
    helpers in posthog.test.persons seed the fake explicitly when creating data.
    """
    import posthog.personhog_client.client as personhog_client_module  # noqa: PLC0415
    from posthog.person_db_router import block_persons_orm, unblock_persons_orm  # noqa: PLC0415

    fake = FakePersonHogClient()
    set_active_fake(fake)
    block_persons_orm()

    # Plain attribute swap instead of mock.patch: this context manager wraps every test in the
    # repo, and mock.patch's MagicMock construction is measurable at that volume. The swap is
    # equivalent — both replace the same module attribute — and tests that patch the client
    # themselves still layer over it and restore this one on exit.
    def _get_fake_client() -> Any:
        return fake

    original_get_client = personhog_client_module.get_personhog_client
    personhog_client_module.get_personhog_client = _get_fake_client  # ty: ignore[invalid-assignment]
    try:
        yield fake
    finally:
        personhog_client_module.get_personhog_client = original_get_client
        unblock_persons_orm()
        set_active_fake(None)
