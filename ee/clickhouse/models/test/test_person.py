from ee.clickhouse.models.person import create_person, get_person_by_distinct_id
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.base import BaseTest


class TestClickhousePerson(ClickhouseTestMixin, BaseTest):
    def test_create_person_no_cache(self) -> None:
        person_id_1 = create_person(
            team_id=self.team.pk,
            distinct_ids=["distinct_1"],
            properties={"email": "my@mail1.com"},
            sync=True,
            cache=False,
        )

        person_id_2 = create_person(
            team_id=self.team.pk,
            distinct_ids=["distinct_1"],
            properties={"email": "my@mail2.com"},
            sync=True,
            cache=False,
        )

        self.assertNotEqual(person_id_1, person_id_2)

        person = get_person_by_distinct_id(team_id=self.team.pk, distinct_id="distinct_1")

        self.assertEqual(str(person["id"]), person_id_2)

        person_id_3 = create_person(
            team_id=self.team.pk,
            distinct_ids=["distinct_1"],
            properties={"email": "my@mail3.com"},
            sync=True,
            cache=False,
        )

        self.assertNotEqual(person_id_1, person_id_3)
        self.assertNotEqual(person_id_2, person_id_3)

        person = get_person_by_distinct_id(team_id=self.team.pk, distinct_id="distinct_1")

        self.assertEqual(str(person["id"]), person_id_3)

    def test_create_person_cache(self) -> None:
        person_id_1 = create_person(
            team_id=self.team.pk,
            distinct_ids=["distinct_1"],
            properties={"email": "my@mail1.com"},
            sync=True,
            cache=True,
        )

        person_id_2 = create_person(
            team_id=self.team.pk,
            distinct_ids=["distinct_1"],
            properties={"email": "my@mail2.com"},
            sync=True,
            cache=True,
        )

        self.assertEqual(person_id_1, person_id_2)

        person = get_person_by_distinct_id(team_id=self.team.pk, distinct_id="distinct_1")

        self.assertEqual(str(person["id"]), person_id_2)

        person_id_3 = create_person(
            team_id=self.team.pk,
            distinct_ids=["distinct_1"],
            properties={"email": "my@mail3.com"},
            sync=True,
            cache=True,
        )

        self.assertEqual(person_id_2, person_id_3)

        person = get_person_by_distinct_id(team_id=self.team.pk, distinct_id="distinct_1")

        self.assertEqual(str(person["id"]), person_id_3)
