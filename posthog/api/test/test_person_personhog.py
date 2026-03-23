"""Integration tests for person API endpoints via the personhog path."""

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest import mock

from rest_framework import status

from posthog.models.person import Person
from posthog.personhog_client.fake_client import fake_personhog_client

UUID_A = "550e8400-e29b-41d4-a716-446655440000"


class TestDeletePropertyPersonhog(APIBaseTest):
    @mock.patch("posthog.api.person.capture_internal")
    def test_uuid_lookup_routes_through_personhog(self, mock_capture):
        mock_capture.return_value = mock.MagicMock(status_code=200)

        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.pk,
                person_id=42,
                uuid=UUID_A,
                distinct_ids=["did1", "did2"],
                properties={"foo": "bar"},
            )

            resp = self.client.post(
                f"/api/person/{UUID_A}/delete_property",
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
            fake.assert_called("get_person_by_uuid")
            fake.assert_called("get_distinct_ids_for_person")

    @mock.patch("posthog.api.person.capture_internal")
    def test_int_pk_bypasses_personhog_uuid_lookup(self, mock_capture):
        mock_capture.return_value = mock.MagicMock(status_code=200)
        person = Person.objects.create(
            team=self.team,
            distinct_ids=["did1"],
            properties={"foo": "bar"},
        )

        with fake_personhog_client() as fake:
            resp = self.client.post(
                f"/api/person/{person.pk}/delete_property",
                {"$unset": "foo"},
            )

            assert resp.status_code == 201
            fake.assert_not_called("get_person_by_uuid")

    def test_uuid_not_found_via_personhog_returns_error(self):
        with fake_personhog_client():
            resp = self.client.post(
                f"/api/person/{UUID_A}/delete_property",
                {"$unset": "foo"},
            )
            assert resp.status_code != 201


class TestBatchByDistinctIdsPersonhog(ClickhouseTestMixin, APIBaseTest):
    def _seed_person(self, fake, *, team_id: int, distinct_ids: list[str], properties: dict | None = None) -> str:
        """Create a person in both the real DB (for other queries) and the fake personhog client."""
        person = _create_person(team=self.team, distinct_ids=distinct_ids, properties=properties or {}, immediate=True)
        flush_persons_and_events()
        fake.add_person(
            team_id=team_id,
            person_id=person.pk,
            uuid=str(person.uuid),
            properties=properties or {},
            distinct_ids=distinct_ids,
            is_identified=person.is_identified,
            created_at=int(person.created_at.timestamp() * 1000) if person.created_at else 0,
        )
        return str(person.uuid)

    def test_happy_path(self) -> None:
        with fake_personhog_client() as fake:
            self._seed_person(
                fake, team_id=self.team.pk, distinct_ids=["user_1"], properties={"email": "user1@example.com"}
            )
            self._seed_person(
                fake, team_id=self.team.pk, distinct_ids=["user_2"], properties={"email": "user2@example.com"}
            )

            response = self.client.post(
                f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
                {"distinct_ids": ["user_1", "user_2"]},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            results = response.json()["results"]
            self.assertIn("user_1", results)
            self.assertIn("user_2", results)
            self.assertEqual(results["user_1"]["properties"]["email"], "user1@example.com")
            self.assertEqual(results["user_2"]["properties"]["email"], "user2@example.com")

            fake.assert_called("get_persons_by_distinct_ids_in_team")

    def test_missing_ids(self) -> None:
        with fake_personhog_client() as fake:
            self._seed_person(
                fake, team_id=self.team.pk, distinct_ids=["existing_user"], properties={"email": "exists@example.com"}
            )

            response = self.client.post(
                f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
                {"distinct_ids": ["existing_user", "nonexistent_1", "nonexistent_2"]},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            results = response.json()["results"]
            self.assertIn("existing_user", results)
            self.assertNotIn("nonexistent_1", results)
            self.assertNotIn("nonexistent_2", results)

    def test_same_person_multiple_ids(self) -> None:
        with fake_personhog_client() as fake:
            self._seed_person(
                fake, team_id=self.team.pk, distinct_ids=["id_a", "id_b"], properties={"email": "multi@example.com"}
            )

            response = self.client.post(
                f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
                {"distinct_ids": ["id_a", "id_b"]},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            results = response.json()["results"]
            self.assertIn("id_a", results)
            self.assertIn("id_b", results)
            self.assertEqual(results["id_a"]["uuid"], results["id_b"]["uuid"])

    def test_empty_list(self) -> None:
        with fake_personhog_client() as fake:
            response = self.client.post(
                f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
                {"distinct_ids": []},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["results"], {})
            fake.assert_not_called("get_persons_by_distinct_ids_in_team")

    def test_invalid_input(self) -> None:
        with fake_personhog_client() as fake:
            response = self.client.post(
                f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
                {"distinct_ids": "not_a_list"},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["results"], {})
            fake.assert_not_called("get_persons_by_distinct_ids_in_team")

    def test_cross_team_isolation(self) -> None:
        from posthog.models import Organization, Team

        other_org, _, _ = Organization.objects.bootstrap(None, name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        with fake_personhog_client() as fake:
            # Seed person in the OTHER team's personhog data
            other_person = _create_person(
                team=other_team,
                distinct_ids=["other_team_user"],
                properties={"email": "other@example.com"},
                immediate=True,
            )
            fake.add_person(
                team_id=other_team.pk,
                person_id=other_person.pk,
                uuid=str(other_person.uuid),
                properties={"email": "other@example.com"},
                distinct_ids=["other_team_user"],
            )

            self._seed_person(
                fake, team_id=self.team.pk, distinct_ids=["my_team_user"], properties={"email": "mine@example.com"}
            )
            flush_persons_and_events()

            response = self.client.post(
                f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
                {"distinct_ids": ["my_team_user", "other_team_user"]},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            results = response.json()["results"]
            self.assertIn("my_team_user", results)
            self.assertNotIn("other_team_user", results)
