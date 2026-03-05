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
boundaries are exercised end-to-end.  The gate is forced ON by default
(override with ``gate_enabled=False``).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from unittest.mock import patch

from posthog.personhog_client.proto.generated.personhog.types.v1 import cohort_pb2, group_pb2, person_pb2


@dataclass
class _Call:
    method: str
    request: Any


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
        is_user_id: bool = False,
        distinct_ids: list[str] | None = None,
    ) -> person_pb2.Person:
        person = person_pb2.Person(
            id=person_id,
            uuid=uuid,
            team_id=team_id,
            properties=json.dumps(properties or {}).encode(),
            created_at=created_at,
            version=version,
            is_identified=is_identified,
            is_user_id=is_user_id,
        )
        self._persons_by_id[(team_id, person_id)] = person
        if uuid:
            self._persons_by_uuid[(team_id, uuid)] = person
        for did in distinct_ids or []:
            self._persons_by_distinct_id[(team_id, did)] = person
            self._distinct_ids.setdefault((team_id, person_id), []).append(
                person_pb2.DistinctIdWithVersion(distinct_id=did, version=0)
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
        seen_person_ids: set[int] = set()
        for did in request.distinct_ids:
            person = self._persons_by_distinct_id.get((request.team_id, did))
            if person and person.id not in seen_person_ids:
                seen_person_ids.add(person.id)
                results.append(person_pb2.PersonWithDistinctIds(distinct_id=did, person=person))
        return person_pb2.PersonsByDistinctIdsInTeamResponse(results=results)

    def get_distinct_ids_for_person(
        self, request: person_pb2.GetDistinctIdsForPersonRequest
    ) -> person_pb2.GetDistinctIdsForPersonResponse:
        self.calls.append(_Call("get_distinct_ids_for_person", request))
        dids = self._distinct_ids.get((request.team_id, request.person_id), [])
        return person_pb2.GetDistinctIdsForPersonResponse(distinct_ids=dids)

    def get_distinct_ids_for_persons(
        self, request: person_pb2.GetDistinctIdsForPersonsRequest
    ) -> person_pb2.GetDistinctIdsForPersonsResponse:
        self.calls.append(_Call("get_distinct_ids_for_persons", request))
        results = []
        for pid in request.person_ids:
            dids = self._distinct_ids.get((request.team_id, pid), [])
            results.append(person_pb2.PersonDistinctIds(person_id=pid, distinct_ids=dids))
        return person_pb2.GetDistinctIdsForPersonsResponse(person_distinct_ids=results)

    def check_cohort_membership(
        self, request: cohort_pb2.CheckCohortMembershipRequest
    ) -> cohort_pb2.CohortMembershipResponse:
        self.calls.append(_Call("check_cohort_membership", request))
        all_memberships = self._cohort_memberships.get(request.person_id, [])
        filtered = [m for m in all_memberships if m.cohort_id in request.cohort_ids]
        return cohort_pb2.CohortMembershipResponse(memberships=filtered)

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
def fake_personhog_client(*, gate_enabled: bool = True):
    """Context manager that patches the personhog client singleton and gate.

    Yields a ``FakePersonHogClient`` that is pre-seeded as empty.
    The gate (``use_personhog()``) returns ``gate_enabled`` for
    every call — no randomness.

    Example::

        with fake_personhog_client() as fake:
            fake.add_group_type_mapping(project_id=1, group_type="org", group_type_index=0)
            result = some_function_that_uses_personhog(1)
    """
    fake = FakePersonHogClient()
    with (
        patch("posthog.personhog_client.client.get_personhog_client", return_value=fake),
        patch("posthog.personhog_client.gate.use_personhog", return_value=gate_enabled),
    ):
        yield fake
