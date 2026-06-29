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
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from unittest.mock import patch

from posthog.models.person.missing_person import uuidFromDistinctId
from posthog.personhog_client.proto.generated.personhog.types.v1 import (
    cohort_pb2,
    feature_flag_pb2,
    group_pb2,
    person_pb2,
)


@dataclass
class _Call:
    method: str
    request: Any
    response: Any = None


class FakePersonHogClient:
    """In-memory fake that implements the same interface as PersonHogClient.

    Stores data as real proto messages and returns real proto responses,
    so the full converter pipeline is exercised.
    """

    def __init__(self) -> None:
        self.calls: list[_Call] = []

        # keyed by (team_id, person_id)
        self._persons_by_id: dict[tuple[int, int], person_pb2.Person] = {}
        # keyed by (team_id, uuid)
        self._persons_by_uuid: dict[tuple[int, str], person_pb2.Person] = {}
        # keyed by (team_id, distinct_id)
        self._persons_by_distinct_id: dict[tuple[int, str], person_pb2.Person] = {}
        # keyed by (team_id, person_id) -> list of DistinctIdWithVersion
        self._distinct_ids: dict[tuple[int, int], list[person_pb2.DistinctIdWithVersion]] = {}

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

        # synthetic ids for persons created by split_person
        self._next_split_person_id = 1_000_000_000

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
        )
        if is_user_id is not None:
            person.is_user_id = is_user_id
        self._persons_by_id[(team_id, person_id)] = person
        if uuid:
            self._persons_by_uuid[(team_id, uuid)] = person
        for did in distinct_ids or []:
            self._persons_by_distinct_id[(team_id, did)] = person
            self._distinct_ids.setdefault((team_id, person_id), []).append(
                person_pb2.DistinctIdWithVersion(distinct_id=did, version=(distinct_id_versions or {}).get(did, 0))
            )
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

    def add_cohort_membership(self, *, person_id: int, cohort_id: int, is_member: bool = True) -> None:
        self._cohort_memberships.setdefault(person_id, []).append(
            cohort_pb2.CohortMembership(cohort_id=cohort_id, is_member=is_member)
        )
        if is_member:
            self._cohort_members[(cohort_id, person_id)] = True

    # ── PersonHogClient interface ────────────────────────────────────

    def close(self) -> None:
        pass

    def get_person(self, request: person_pb2.GetPersonRequest) -> person_pb2.GetPersonResponse:
        self.calls.append(_Call("get_person", request))
        person = self._persons_by_id.get((request.team_id, request.person_id))
        return person_pb2.GetPersonResponse(person=person)

    def get_persons(self, request: person_pb2.GetPersonsRequest) -> person_pb2.PersonsResponse:
        self.calls.append(_Call("get_persons", request))
        found = []
        missing = []
        for pid in request.person_ids:
            person = self._persons_by_id.get((request.team_id, pid))
            if person:
                found.append(person)
            else:
                missing.append(pid)
        return person_pb2.PersonsResponse(persons=found, missing_ids=missing)

    def get_person_by_uuid(self, request: person_pb2.GetPersonByUuidRequest) -> person_pb2.GetPersonResponse:
        self.calls.append(_Call("get_person_by_uuid", request))
        person = self._persons_by_uuid.get((request.team_id, request.uuid))
        return person_pb2.GetPersonResponse(person=person)

    def get_persons_by_uuids(self, request: person_pb2.GetPersonsByUuidsRequest) -> person_pb2.PersonsResponse:
        self.calls.append(_Call("get_persons_by_uuids", request))
        found = []
        missing_ids: list[int] = []
        for uuid in request.uuids:
            person = self._persons_by_uuid.get((request.team_id, uuid))
            if person:
                found.append(person)
        return person_pb2.PersonsResponse(persons=found, missing_ids=missing_ids)

    def get_person_by_distinct_id(
        self, request: person_pb2.GetPersonByDistinctIdRequest
    ) -> person_pb2.GetPersonResponse:
        self.calls.append(_Call("get_person_by_distinct_id", request))
        person = self._persons_by_distinct_id.get((request.team_id, request.distinct_id))
        return person_pb2.GetPersonResponse(person=person)

    def get_persons_by_distinct_ids_in_team(
        self, request: person_pb2.GetPersonsByDistinctIdsInTeamRequest
    ) -> person_pb2.PersonsByDistinctIdsInTeamResponse:
        self.calls.append(_Call("get_persons_by_distinct_ids_in_team", request))
        results = []
        for did in request.distinct_ids:
            person = self._persons_by_distinct_id.get((request.team_id, did))
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
        dids = self._distinct_ids.get((request.team_id, request.person_id), [])
        limit = request.limit if request.HasField("limit") and request.limit > 0 else None
        if limit is not None:
            dids = dids[:limit]
        return person_pb2.GetDistinctIdsForPersonResponse(distinct_ids=dids)

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
                dids = dids[:limit]
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
        self._groups[(request.team_id, request.group_type_index, request.group_key)] = group
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

    def delete_persons(
        self, request: person_pb2.DeletePersonsRequest, timeout: float | None = None
    ) -> person_pb2.DeletePersonsResponse:
        self.calls.append(_Call("delete_persons", request))
        deleted_count = 0
        for uuid in request.person_uuids:
            person = self._persons_by_uuid.pop((request.team_id, uuid), None)
            if person is None:
                continue
            deleted_count += 1
            self._persons_by_id.pop((request.team_id, person.id), None)
            # Remove distinct_id mappings
            dids = self._distinct_ids.pop((request.team_id, person.id), [])
            for did in dids:
                self._persons_by_distinct_id.pop((request.team_id, did.distinct_id), None)
        return person_pb2.DeletePersonsResponse(deleted_count=deleted_count)

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
        for team_id, uuid, person in to_delete:
            self._persons_by_uuid.pop((team_id, uuid), None)
            self._persons_by_id.pop((team_id, person.id), None)
            dids = self._distinct_ids.pop((team_id, person.id), [])
            for did in dids:
                self._persons_by_distinct_id.pop((team_id, did.distinct_id), None)
            deleted_count += 1
        response = person_pb2.DeletePersonsBatchForTeamResponse(deleted_count=deleted_count)
        self.calls.append(_Call("delete_persons_batch_for_team", request, response))
        return response

    def delete_personless_distinct_ids_batch_for_team(
        self, request: person_pb2.DeletePersonlessDistinctIdsBatchForTeamRequest, timeout: float | None = None
    ) -> person_pb2.DeletePersonlessDistinctIdsBatchForTeamResponse:
        # The fake does not model personless distinct IDs, so this records the
        # call for assertions and reports nothing deleted.
        response = person_pb2.DeletePersonlessDistinctIdsBatchForTeamResponse(deleted_count=0)
        self.calls.append(_Call("delete_personless_distinct_ids_batch_for_team", request, response))
        return response

    # ── Person split ──────────────────────────────────────────────────

    def split_person(
        self, request: person_pb2.SplitPersonRequest, timeout: float | None = None
    ) -> person_pb2.SplitPersonResponse:
        """Stateful mirror of the real RPC: validates ownership, creates new
        persons with deterministic UUIDv5s (preserving created_at for
        pre-existing ones), moves the distinct_ids, and bumps versions by 101.
        Results are returned in request order, like the real service.
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
            if existing is not None:
                existing.version = new_person_version
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
                    new_person_version=new_person_version,
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
    from posthog.person_db_router import block_persons_orm, unblock_persons_orm  # noqa: PLC0415

    fake = FakePersonHogClient()
    set_active_fake(fake)
    block_persons_orm()
    with patch("posthog.personhog_client.client.get_personhog_client", return_value=fake):
        try:
            yield fake
        finally:
            unblock_persons_orm()
            set_active_fake(None)
