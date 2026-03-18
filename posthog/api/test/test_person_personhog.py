"""Integration tests for the person API batch_by_distinct_ids endpoint via the personhog path.

These mirror the test cases in TestPerson.test_batch_by_distinct_ids_* to ensure
the personhog code path returns identical results to the ORM path.
"""

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events

from rest_framework import status

from posthog.personhog_client.fake_client import fake_personhog_client


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
