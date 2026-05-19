"""Tests that person API endpoints produce identical results
via the ORM and personhog paths.

Covers retrieve, update, split, delete_property, batch_by_distinct_ids, and
person deletion — extracted from test_person.py so both code paths are
validated with @parameterized_class.
"""

from posthog.test.base import APIBaseTest
from unittest import mock

from parameterized import parameterized_class
from rest_framework import status

from posthog.models import Cohort, Organization, Person, Team
from posthog.models.person import PersonDistinctId
from posthog.personhog_client.test_helpers import PersonhogTestMixin

UUID_NONEXISTENT = "550e8400-e29b-41d4-a716-446655440000"


@parameterized_class(("personhog",), [(False,), (True,)])
class TestRetrievePerson(PersonhogTestMixin, APIBaseTest):
    def test_retrieve_by_uuid(self):
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did-1", "did-2"],
            properties={"email": "test@example.com"},
        )

        resp = self.client.get(f"/api/person/{person.uuid}/")

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["uuid"] == str(person.uuid)
        assert data["properties"]["email"] == "test@example.com"
        assert set(data["distinct_ids"]) == {"did-1", "did-2"}
        self._assert_personhog_called("get_person_by_uuid")

    def test_retrieve_by_pk(self):
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did-1"],
            properties={"name": "Test User"},
        )

        resp = self.client.get(f"/api/person/{person.pk}/")

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["uuid"] == str(person.uuid)
        assert data["properties"]["name"] == "Test User"
        self._assert_personhog_not_called("get_person_by_uuid")
        self._assert_personhog_called("get_person")

    def test_retrieve_nonexistent_returns_404(self):
        resp = self.client.get(f"/api/person/{UUID_NONEXISTENT}/")

        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_retrieve_invalid_id_returns_validation_error(self):
        resp = self.client.get("/api/person/not-a-valid-id/")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "does not look like a personID" in resp.json().get("detail", "")

    def test_retrieve_cross_team_isolation(self):
        other_org, _, _ = Organization.objects.bootstrap(None, name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_person = self._seed_person(team=other_team, distinct_ids=["other-did"])

        resp = self.client.get(f"/api/person/{other_person.uuid}/")

        assert resp.status_code == status.HTTP_404_NOT_FOUND


@parameterized_class(("personhog",), [(False,), (True,)])
class TestUpdatePerson(PersonhogTestMixin, APIBaseTest):
    @mock.patch("posthog.api.person.capture_internal")
    def test_update_properties_by_uuid(self, mock_capture):
        mock_capture.return_value = mock.MagicMock(status_code=200)
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did-1"],
            properties={"existing": "value"},
        )

        resp = self.client.patch(
            f"/api/person/{person.uuid}/",
            {"properties": {"new_key": "new_value"}},
            format="json",
        )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args[1]
        assert call_kwargs["distinct_id"] == "did-1"
        assert call_kwargs["properties"] == {"$set": {"new_key": "new_value"}}
        self._assert_personhog_called("get_person_by_uuid")

    @mock.patch("posthog.api.person.capture_internal")
    def test_update_properties_by_pk(self, mock_capture):
        mock_capture.return_value = mock.MagicMock(status_code=200)
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did-1"],
            properties={},
        )

        resp = self.client.patch(
            f"/api/person/{person.pk}/",
            {"properties": {"key": "val"}},
            format="json",
        )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        self._assert_personhog_not_called("get_person_by_uuid")
        self._assert_personhog_called("get_person")


@parameterized_class(("personhog",), [(False,), (True,)])
class TestSplitPerson(PersonhogTestMixin, APIBaseTest):
    @mock.patch("posthog.api.person.split_person")
    def test_split_by_uuid(self, mock_split):
        mock_split.delay = mock.MagicMock()
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did-1", "did-2", "did-3"],
        )

        resp = self.client.post(f"/api/person/{person.uuid}/split/")

        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json() == {"success": True}
        mock_split.delay.assert_called_once_with(
            person.pk,
            self.team.pk,
            None,
            None,
            distinct_ids_to_split=None,
        )
        self._assert_personhog_called("get_person_by_uuid")

    @mock.patch("posthog.api.person.split_person")
    def test_split_nonexistent_returns_404(self, mock_split):
        resp = self.client.post(f"/api/person/{UUID_NONEXISTENT}/split/")

        assert resp.status_code == status.HTTP_404_NOT_FOUND
        mock_split.delay.assert_not_called()


@parameterized_class(("personhog",), [(False,), (True,)])
class TestCohortsByPerson(PersonhogTestMixin, APIBaseTest):
    def test_cohorts_by_uuid(self):
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did-1"],
        )
        cohort = Cohort.objects.create(team=self.team, name="Test Cohort")

        with mock.patch(
            "posthog.api.person.get_all_cohort_ids_by_person_uuid",
            return_value=[cohort.pk],
        ):
            resp = self.client.get(f"/api/person/cohorts/?person_id={person.uuid}")

        assert resp.status_code == status.HTTP_200_OK
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["name"] == "Test Cohort"
        self._assert_personhog_called("get_person_by_uuid")

    def test_cohorts_nonexistent_person_returns_404(self):
        with mock.patch(
            "posthog.api.person.get_all_cohort_ids_by_person_uuid",
            return_value=[],
        ):
            resp = self.client.get(f"/api/person/cohorts/?person_id={UUID_NONEXISTENT}")

        assert resp.status_code == status.HTTP_404_NOT_FOUND


@parameterized_class(("personhog",), [(False,), (True,)])
class TestDeleteProperty(PersonhogTestMixin, APIBaseTest):
    @mock.patch("posthog.api.person.capture_internal")
    def test_uuid_lookup(self, mock_capture):
        mock_capture.return_value = mock.MagicMock(status_code=200)
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did1", "did2"],
            properties={"foo": "bar"},
        )

        resp = self.client.post(
            f"/api/person/{person.uuid}/delete_property",
            {"$unset": "foo"},
        )

        assert resp.status_code == 201
        mock_capture.assert_called_once_with(
            token=self.team.api_token,
            event_name="$delete_person_property",
            event_source="person_viewset",
            distinct_id="did1",
            timestamp=mock.ANY,
            properties={"$unset": ["foo"]},
            process_person_profile=True,
        )
        self._assert_personhog_called("get_person_by_uuid")
        self._assert_personhog_called("get_distinct_ids_for_person")

    @mock.patch("posthog.api.person.capture_internal")
    def test_integer_pk_lookup(self, mock_capture):
        mock_capture.return_value = mock.MagicMock(status_code=200)
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did1"],
            properties={"foo": "bar"},
        )

        resp = self.client.post(
            f"/api/person/{person.pk}/delete_property",
            {"$unset": "foo"},
        )

        assert resp.status_code == 201
        self._assert_personhog_not_called("get_person_by_uuid")
        self._assert_personhog_called("get_person")

    def test_uuid_not_found_returns_error(self):
        resp = self.client.post(
            f"/api/person/{UUID_NONEXISTENT}/delete_property",
            {"$unset": "foo"},
        )

        assert resp.status_code != 201


@parameterized_class(("personhog",), [(False,), (True,)])
class TestBatchByDistinctIds(PersonhogTestMixin, APIBaseTest):
    def test_happy_path(self):
        self._seed_person(team=self.team, distinct_ids=["user_1"], properties={"email": "user1@example.com"})
        self._seed_person(team=self.team, distinct_ids=["user_2"], properties={"email": "user2@example.com"})

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": ["user_1", "user_2"]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert "user_1" in results
        assert "user_2" in results
        assert results["user_1"]["properties"]["email"] == "user1@example.com"
        assert results["user_2"]["properties"]["email"] == "user2@example.com"
        self._assert_personhog_called("get_persons_by_distinct_ids_in_team")

    def test_missing_ids(self):
        self._seed_person(team=self.team, distinct_ids=["existing_user"], properties={"email": "exists@example.com"})

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": ["existing_user", "nonexistent_1", "nonexistent_2"]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert "existing_user" in results
        assert "nonexistent_1" not in results
        assert "nonexistent_2" not in results

    def test_same_person_multiple_ids(self):
        self._seed_person(team=self.team, distinct_ids=["id_a", "id_b"], properties={"email": "multi@example.com"})

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": ["id_a", "id_b"]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert "id_a" in results
        assert "id_b" in results
        assert results["id_a"]["uuid"] == results["id_b"]["uuid"]

    def test_empty_list(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": []},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == {}
        self._assert_personhog_not_called("get_persons_by_distinct_ids_in_team")

    def test_invalid_input(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": "not_a_list"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == {}
        self._assert_personhog_not_called("get_persons_by_distinct_ids_in_team")

    def test_cross_team_isolation(self):
        other_org, _, _ = Organization.objects.bootstrap(None, name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        self._seed_person(team=other_team, distinct_ids=["other_team_user"], properties={"email": "other@example.com"})
        self._seed_person(team=self.team, distinct_ids=["my_team_user"], properties={"email": "mine@example.com"})

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": ["my_team_user", "other_team_user"]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert "my_team_user" in results
        assert "other_team_user" not in results

    def test_truncates_at_max_batch_size(self):
        distinct_ids = [f"user_{i}" for i in range(201)]
        self._seed_person(team=self.team, distinct_ids=[distinct_ids[200]], properties={"email": "last@example.com"})

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": distinct_ids},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert distinct_ids[200] not in results


@parameterized_class(("personhog",), [(False,), (True,)])
class TestDestroyPerson(PersonhogTestMixin, APIBaseTest):
    def test_destroy_returns_202(self):
        person = self._seed_person(team=self.team, distinct_ids=["did-1"])

        resp = self.client.delete(f"/api/person/{person.uuid}/")

        assert resp.status_code == status.HTTP_202_ACCEPTED
        assert resp.content == b""
        calls = self._assert_personhog_called("delete_persons")
        if calls:
            assert calls[0].request.team_id == self.team.pk
            assert list(calls[0].request.person_uuids) == [str(person.uuid)]

    def test_destroy_removes_person_from_postgres(self):
        person = self._seed_person(team=self.team, distinct_ids=["did-1", "did-2"])

        self.client.delete(f"/api/person/{person.uuid}/")

        calls = self._assert_personhog_called("delete_persons")
        if calls:
            assert calls[0].request.team_id == self.team.pk
            assert list(calls[0].request.person_uuids) == [str(person.uuid)]

        if not self.personhog:
            assert Person.objects.filter(team_id=self.team.pk, uuid=person.uuid).count() == 0
            assert PersonDistinctId.objects.filter(team_id=self.team.pk, person_id=person.pk).count() == 0

    def test_destroy_nonexistent_returns_404(self):
        resp = self.client.delete(f"/api/person/{UUID_NONEXISTENT}/")

        assert resp.status_code == status.HTTP_404_NOT_FOUND
        self._assert_personhog_not_called("delete_persons")

    def test_destroy_with_keep_person_skips_delete(self):
        person = self._seed_person(team=self.team, distinct_ids=["did-1"])

        resp = self.client.delete(f"/api/person/{person.uuid}/?keep_person=true&delete_events=true")

        assert resp.status_code == status.HTTP_202_ACCEPTED
        assert Person.objects.filter(team_id=self.team.pk, uuid=person.uuid).count() == 1
        self._assert_personhog_not_called("delete_persons")


@parameterized_class(("personhog",), [(False,), (True,)])
class TestBulkDeletePersons(PersonhogTestMixin, APIBaseTest):
    def test_bulk_delete_by_ids(self):
        p1 = self._seed_person(team=self.team, distinct_ids=["did-1"])
        p2 = self._seed_person(team=self.team, distinct_ids=["did-2"])

        resp = self.client.post(
            "/api/person/bulk_delete/",
            {"ids": [str(p1.uuid), str(p2.uuid)]},
        )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        assert data["persons_found"] == 2
        assert data["persons_deleted"] == 2
        assert data["deletion_errors"] == []
        assert data["events_queued_for_deletion"] is False
        assert data["recordings_queued_for_deletion"] is False

        calls = self._assert_personhog_called("delete_persons")
        if calls:
            assert calls[0].request.team_id == self.team.pk
            assert set(calls[0].request.person_uuids) == {str(p1.uuid), str(p2.uuid)}

        if not self.personhog:
            assert Person.objects.filter(team_id=self.team.pk).count() == 0
            assert PersonDistinctId.objects.filter(team_id=self.team.pk).count() == 0

    def test_bulk_delete_by_distinct_ids(self):
        p1 = self._seed_person(team=self.team, distinct_ids=["did-1"])
        p2 = self._seed_person(team=self.team, distinct_ids=["did-2"])

        resp = self.client.post(
            "/api/person/bulk_delete/",
            {"distinct_ids": ["did-1", "did-2"]},
        )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        assert data["persons_found"] == 2
        assert data["persons_deleted"] == 2
        assert data["deletion_errors"] == []

        calls = self._assert_personhog_called("delete_persons")
        if calls:
            assert calls[0].request.team_id == self.team.pk
            assert set(calls[0].request.person_uuids) == {str(p1.uuid), str(p2.uuid)}

        if not self.personhog:
            assert Person.objects.filter(team_id=self.team.pk).count() == 0

    def test_bulk_delete_with_keep_person(self):
        p1 = self._seed_person(team=self.team, distinct_ids=["did-1"])

        resp = self.client.post(
            "/api/person/bulk_delete/",
            {"ids": [str(p1.uuid)], "keep_person": True, "delete_events": True},
        )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        assert data["persons_found"] == 1
        assert data["persons_deleted"] == 0
        assert data["events_queued_for_deletion"] is True
        assert data["deletion_errors"] == []
        assert Person.objects.filter(team_id=self.team.pk, uuid=p1.uuid).count() == 1
        self._assert_personhog_not_called("delete_persons")

    def test_cross_team_isolation(self):
        other_org, _, _ = Organization.objects.bootstrap(None, name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_person = self._seed_person(team=other_team, distinct_ids=["other-did"])

        p1 = self._seed_person(team=self.team, distinct_ids=["did-1"])

        resp = self.client.post(
            "/api/person/bulk_delete/",
            {"ids": [str(p1.uuid)]},
        )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        assert data["persons_found"] == 1
        assert data["persons_deleted"] == 1
        assert data["deletion_errors"] == []

        calls = self._assert_personhog_called("delete_persons")
        if calls:
            assert calls[0].request.team_id == self.team.pk
            assert list(calls[0].request.person_uuids) == [str(p1.uuid)]
        # Other team's person should be untouched
        assert Person.objects.filter(team_id=other_team.pk, uuid=other_person.uuid).count() == 1

    @mock.patch("posthog.models.person.bulk_delete.delete_person")
    def test_bulk_delete_partial_failure_only_deletes_successful_from_postgres(self, mock_delete_person):
        p1 = self._seed_person(team=self.team, distinct_ids=["did-1"])
        p2 = self._seed_person(team=self.team, distinct_ids=["did-2"])

        mock_delete_person.side_effect = [Exception("CH write failed"), None]

        resp = self.client.post(
            "/api/person/bulk_delete/",
            {"ids": [str(p1.uuid), str(p2.uuid)]},
        )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        assert data["persons_found"] == 2
        assert data["persons_deleted"] == 1
        assert len(data["deletion_errors"]) == 1
        assert data["deletion_errors"][0]["person_uuid"] == str(p1.uuid)

        calls = self._assert_personhog_called("delete_persons")
        if calls:
            # Only the successful person should be sent to personhog for PG deletion
            assert list(calls[0].request.person_uuids) == [str(p2.uuid)]

        if not self.personhog:
            # p1 should still exist (CH delete failed), p2 should be gone
            assert Person.objects.filter(team_id=self.team.pk, uuid=p1.uuid).count() == 1
            assert Person.objects.filter(team_id=self.team.pk, uuid=p2.uuid).count() == 0
