import json

import pytest

from posthog.personhog_client.fake_client import FakePersonHogClient, fake_personhog_client
from posthog.personhog_client.proto.generated.personhog.types.v1 import cohort_pb2, common_pb2, group_pb2, person_pb2


class TestFakePersonHogClientPersons:
    def setup_method(self):
        self.client = FakePersonHogClient()
        self.client.add_person(team_id=1, person_id=10, uuid="abc-123", distinct_ids=["user@example.com", "anon-1"])
        self.client.add_person(team_id=1, person_id=20, uuid="def-456", distinct_ids=["user2@example.com"])

    def test_get_person_found(self):
        resp = self.client.get_person(person_pb2.GetPersonRequest(team_id=1, person_id=10))
        assert resp.person.uuid == "abc-123"

    def test_get_person_missing(self):
        resp = self.client.get_person(person_pb2.GetPersonRequest(team_id=1, person_id=999))
        assert not resp.HasField("person")

    def test_get_person_wrong_team(self):
        resp = self.client.get_person(person_pb2.GetPersonRequest(team_id=99, person_id=10))
        assert not resp.HasField("person")

    def test_get_persons_partial(self):
        resp = self.client.get_persons(person_pb2.GetPersonsRequest(team_id=1, person_ids=[10, 999]))
        assert len(resp.persons) == 1
        assert resp.persons[0].id == 10
        assert list(resp.missing_ids) == [999]

    def test_get_person_by_uuid(self):
        resp = self.client.get_person_by_uuid(person_pb2.GetPersonByUuidRequest(team_id=1, uuid="def-456"))
        assert resp.person.id == 20

    def test_get_person_by_distinct_id(self):
        resp = self.client.get_person_by_distinct_id(
            person_pb2.GetPersonByDistinctIdRequest(team_id=1, distinct_id="user@example.com")
        )
        assert resp.person.id == 10

    def test_get_distinct_ids_for_person(self):
        resp = self.client.get_distinct_ids_for_person(
            person_pb2.GetDistinctIdsForPersonRequest(team_id=1, person_id=10)
        )
        assert [d.distinct_id for d in resp.distinct_ids] == ["user@example.com", "anon-1"]

    def test_get_distinct_ids_for_person_missing(self):
        resp = self.client.get_distinct_ids_for_person(
            person_pb2.GetDistinctIdsForPersonRequest(team_id=1, person_id=999)
        )
        assert len(resp.distinct_ids) == 0

    def test_get_distinct_ids_for_persons(self):
        resp = self.client.get_distinct_ids_for_persons(
            person_pb2.GetDistinctIdsForPersonsRequest(team_id=1, person_ids=[10, 20])
        )
        assert len(resp.person_distinct_ids) == 2
        assert resp.person_distinct_ids[0].person_id == 10
        assert len(resp.person_distinct_ids[0].distinct_ids) == 2

    def test_get_persons_by_distinct_ids_in_team(self):
        resp = self.client.get_persons_by_distinct_ids_in_team(
            person_pb2.GetPersonsByDistinctIdsInTeamRequest(
                team_id=1, distinct_ids=["user@example.com", "anon-1", "user2@example.com"]
            )
        )
        assert len(resp.results) == 2
        person_ids = {r.person.id for r in resp.results}
        assert person_ids == {10, 20}


class TestFakePersonHogClientGroups:
    def setup_method(self):
        self.client = FakePersonHogClient()
        self.client.add_group(team_id=1, group_type_index=0, group_key="org:1", group_properties={"name": "Acme"})
        self.client.add_group(team_id=1, group_type_index=0, group_key="org:2")

    def test_get_group_found(self):
        resp = self.client.get_group(group_pb2.GetGroupRequest(team_id=1, group_type_index=0, group_key="org:1"))
        assert json.loads(resp.group.group_properties) == {"name": "Acme"}

    def test_get_group_missing(self):
        resp = self.client.get_group(group_pb2.GetGroupRequest(team_id=1, group_type_index=0, group_key="org:99"))
        assert not resp.HasField("group")

    def test_get_groups(self):
        resp = self.client.get_groups(
            group_pb2.GetGroupsRequest(
                team_id=1,
                group_identifiers=[
                    common_pb2.GroupIdentifier(group_type_index=0, group_key="org:1"),
                    common_pb2.GroupIdentifier(group_type_index=0, group_key="org:missing"),
                ],
            )
        )
        assert len(resp.groups) == 1
        assert len(resp.missing_groups) == 1

    def test_get_groups_batch(self):
        resp = self.client.get_groups_batch(
            group_pb2.GetGroupsBatchRequest(
                keys=[
                    common_pb2.GroupKey(team_id=1, group_type_index=0, group_key="org:1"),
                    common_pb2.GroupKey(team_id=1, group_type_index=0, group_key="org:2"),
                ]
            )
        )
        assert len(resp.results) == 2


class TestFakePersonHogClientGroupTypeMappings:
    def setup_method(self):
        self.client = FakePersonHogClient()
        self.client.add_group_type_mapping(
            project_id=100,
            team_id=1,
            group_type="organization",
            group_type_index=0,
            name_singular="Organization",
        )
        self.client.add_group_type_mapping(project_id=100, team_id=1, group_type="company", group_type_index=1)

    def test_by_project_id(self):
        resp = self.client.get_group_type_mappings_by_project_id(
            group_pb2.GetGroupTypeMappingsByProjectIdRequest(project_id=100)
        )
        assert len(resp.mappings) == 2
        assert resp.mappings[0].group_type == "organization"

    def test_by_project_id_empty(self):
        resp = self.client.get_group_type_mappings_by_project_id(
            group_pb2.GetGroupTypeMappingsByProjectIdRequest(project_id=999)
        )
        assert len(resp.mappings) == 0

    def test_by_team_id(self):
        resp = self.client.get_group_type_mappings_by_team_id(group_pb2.GetGroupTypeMappingsByTeamIdRequest(team_id=1))
        assert len(resp.mappings) == 2

    def test_by_project_ids_batch(self):
        resp = self.client.get_group_type_mappings_by_project_ids(
            group_pb2.GetGroupTypeMappingsByProjectIdsRequest(project_ids=[100, 999])
        )
        assert len(resp.results) == 2
        assert len(resp.results[0].mappings) == 2
        assert len(resp.results[1].mappings) == 0

    def test_by_team_ids_batch(self):
        resp = self.client.get_group_type_mappings_by_team_ids(
            group_pb2.GetGroupTypeMappingsByTeamIdsRequest(team_ids=[1, 999])
        )
        assert len(resp.results) == 2
        assert len(resp.results[0].mappings) == 2
        assert len(resp.results[1].mappings) == 0


class TestFakePersonHogClientCohorts:
    def setup_method(self):
        self.client = FakePersonHogClient()
        self.client.add_cohort_membership(person_id=10, cohort_id=1, is_member=True)
        self.client.add_cohort_membership(person_id=10, cohort_id=2, is_member=False)

    def test_check_membership(self):
        resp = self.client.check_cohort_membership(
            cohort_pb2.CheckCohortMembershipRequest(person_id=10, cohort_ids=[1, 2])
        )
        assert len(resp.memberships) == 2
        by_id = {m.cohort_id: m.is_member for m in resp.memberships}
        assert by_id == {1: True, 2: False}

    def test_check_membership_filters_cohort_ids(self):
        resp = self.client.check_cohort_membership(
            cohort_pb2.CheckCohortMembershipRequest(person_id=10, cohort_ids=[1])
        )
        assert len(resp.memberships) == 1

    def test_check_membership_unknown_person(self):
        resp = self.client.check_cohort_membership(
            cohort_pb2.CheckCohortMembershipRequest(person_id=999, cohort_ids=[1])
        )
        assert len(resp.memberships) == 0


class TestCallTracking:
    def test_assert_called(self):
        client = FakePersonHogClient()
        client.get_group_type_mappings_by_project_id(group_pb2.GetGroupTypeMappingsByProjectIdRequest(project_id=1))
        calls = client.assert_called("get_group_type_mappings_by_project_id", times=1)
        assert calls[0].request.project_id == 1

    def test_assert_called_fails(self):
        client = FakePersonHogClient()
        with pytest.raises(AssertionError, match="never called"):
            client.assert_called("get_person")

    def test_assert_not_called(self):
        client = FakePersonHogClient()
        client.assert_not_called("get_person")

    def test_assert_not_called_fails(self):
        client = FakePersonHogClient()
        client.get_person(person_pb2.GetPersonRequest(team_id=1, person_id=1))
        with pytest.raises(AssertionError, match="called 1 time"):
            client.assert_not_called("get_person")


class TestFakePersonhogClientContextManager:
    def test_patches_get_personhog_client(self):
        with fake_personhog_client() as fake:
            fake.add_group_type_mapping(project_id=1, group_type="org", group_type_index=0)

            from posthog.personhog_client.client import get_personhog_client

            client = get_personhog_client()
            assert client is fake

    def test_patches_gate(self):
        with fake_personhog_client(gate_enabled=True):
            from posthog.personhog_client.gate import use_personhog

            assert use_personhog() is True

        with fake_personhog_client(gate_enabled=False):
            from posthog.personhog_client.gate import use_personhog

            assert use_personhog() is False
