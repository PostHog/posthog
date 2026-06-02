from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db.models.signals import post_save

from posthog.models import Person
from posthog.models.person import PersonDistinctId
from posthog.models.person.util import person_created, person_distinct_id_created
from posthog.tasks.split_person import split_person


@patch("posthog.models.person.util.create_person")
@patch("posthog.models.person.util.create_person_distinct_id")
class TestSplitPersonTask(BaseTest):
    def setUp(self):
        super().setUp()
        post_save.disconnect(person_created, sender=Person)
        post_save.disconnect(person_distinct_id_created, sender=PersonDistinctId)

    def tearDown(self):
        post_save.connect(person_created, sender=Person)
        post_save.connect(person_distinct_id_created, sender=PersonDistinctId)
        super().tearDown()

    def _create_person_with_distinct_ids(self, distinct_ids: list[str], mock_create_pdi, mock_create_person) -> Person:
        person = Person.objects.create(team=self.team, properties={}, version=0)
        for distinct_id in distinct_ids:
            PersonDistinctId.objects.create(team=self.team, person=person, distinct_id=distinct_id)
        mock_create_pdi.reset_mock()
        mock_create_person.reset_mock()
        return person

    def test_new_signature_fetches_person_via_get_person_by_id(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(["id1", "id2"], mock_create_pdi, mock_create_person)

        with patch(
            "posthog.tasks.split_person.get_person_by_id",
            wraps=lambda tid, pid: Person.objects.get(team_id=tid, pk=pid),
        ) as mock_get:
            split_person(person.id, self.team.id, "id1")

        mock_get.assert_called_once_with(self.team.id, person.id)

        pdi_id1 = PersonDistinctId.objects.get(team=self.team, distinct_id="id1")
        pdi_id2 = PersonDistinctId.objects.get(team=self.team, distinct_id="id2")
        assert pdi_id1.person_id == person.id
        assert pdi_id2.person_id != person.id

    def test_new_signature_raises_does_not_exist_for_missing_person(self, mock_create_pdi, mock_create_person):
        with self.assertRaises(Person.DoesNotExist):
            split_person(999999, self.team.id, None)

    def test_new_signature_with_distinct_ids_to_split(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(["a", "b", "c"], mock_create_pdi, mock_create_person)

        split_person(person.id, self.team.id, None, None, distinct_ids_to_split=["b"])

        assert PersonDistinctId.objects.get(team=self.team, distinct_id="a").person_id == person.id
        assert PersonDistinctId.objects.get(team=self.team, distinct_id="b").person_id != person.id
        assert PersonDistinctId.objects.get(team=self.team, distinct_id="c").person_id == person.id

    def test_legacy_signature_falls_back_to_pdi_lookup(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(["id1", "id2"], mock_create_pdi, mock_create_person)

        split_person(person.id)

        pdi_id2 = PersonDistinctId.objects.get(team=self.team, distinct_id="id2")
        assert pdi_id2.person_id != person.id

    def test_legacy_signature_raises_for_unknown_person_id(self, mock_create_pdi, mock_create_person):
        with self.assertRaises(ValueError, msg="Cannot find team_id"):
            split_person(999999)
