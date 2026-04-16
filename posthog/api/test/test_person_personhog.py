"""Tests that person API endpoints produce identical results
via the ORM and personhog paths.

Covers delete_property and batch_by_distinct_ids — extracted from
test_person.py so both code paths are validated with @parameterized_class.
"""

from posthog.test.base import APIBaseTest
from unittest import mock

from parameterized import parameterized_class
from rest_framework import status

from posthog.models import Organization, Team
from posthog.personhog_client.test_helpers import PersonhogTestMixin

UUID_NONEXISTENT = "550e8400-e29b-41d4-a716-446655440000"


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
