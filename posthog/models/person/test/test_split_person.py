from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db.models.signals import post_save

from posthog.models import Person
from posthog.models.person import PersonDistinctId
from posthog.models.person.missing_person import uuidFromDistinctId
from posthog.models.person.util import person_created, person_distinct_id_created


@patch("posthog.models.person.util.create_person")
@patch("posthog.models.person.util.create_person_distinct_id")
class TestSplitPerson(BaseTest):
    def setUp(self):
        super().setUp()
        # Disconnect test-only post_save signals (see posthog/models/person/util.py)
        # that automatically call create_person/create_person_distinct_id on every
        # ORM save. split_person publishes to Kafka explicitly, so these signals
        # would double-count calls and make assertions unreliable.
        post_save.disconnect(person_created, sender=Person)
        post_save.disconnect(person_distinct_id_created, sender=PersonDistinctId)

    def tearDown(self):
        post_save.connect(person_created, sender=Person)
        post_save.connect(person_distinct_id_created, sender=PersonDistinctId)
        super().tearDown()

    def _create_person_with_distinct_ids(
        self,
        distinct_ids: list[str],
        mock_create_pdi,
        mock_create_person,
        properties: dict | None = None,
        version: int = 0,
    ) -> Person:
        person = Person.objects.create(
            team=self.team,
            properties=properties or {},
            version=version,
        )
        for distinct_id in distinct_ids:
            PersonDistinctId.objects.create(
                team=self.team,
                person=person,
                distinct_id=distinct_id,
            )
        # Reset mocks after setup so post_save signal calls from setup don't count
        mock_create_pdi.reset_mock()
        mock_create_person.reset_mock()
        return person

    def test_split_with_main_distinct_id(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(
            ["id1", "id2", "id3"],
            mock_create_pdi,
            mock_create_person,
            properties={"email": "test@example.com", "name": "Test"},
        )

        person.split_person(main_distinct_id="id1")

        pdi_id1 = PersonDistinctId.objects.get(team=self.team, distinct_id="id1")
        pdi_id2 = PersonDistinctId.objects.get(team=self.team, distinct_id="id2")
        pdi_id3 = PersonDistinctId.objects.get(team=self.team, distinct_id="id3")

        assert pdi_id1.person_id == person.id
        assert pdi_id2.person_id != person.id
        assert pdi_id3.person_id != person.id
        assert pdi_id2.person_id != pdi_id3.person_id

        # Original person keeps its properties when main_distinct_id is provided
        person.refresh_from_db()
        assert person.properties == {"email": "test@example.com", "name": "Test"}

        # New persons have empty properties
        new_person_2 = Person.objects.get(team_id=self.team.id, id=pdi_id2.person_id)
        new_person_3 = Person.objects.get(team_id=self.team.id, id=pdi_id3.person_id)
        assert new_person_2.properties == {}
        assert new_person_3.properties == {}

        assert mock_create_pdi.call_count == 2
        assert mock_create_person.call_count == 2

    def test_split_without_main_distinct_id_clears_properties(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(
            ["id1", "id2"],
            mock_create_pdi,
            mock_create_person,
            properties={"email": "test@example.com"},
        )

        person.split_person(main_distinct_id=None)

        person.refresh_from_db()
        assert person.properties == {}

        pdi_id1 = PersonDistinctId.objects.get(team=self.team, distinct_id="id1")
        pdi_id2 = PersonDistinctId.objects.get(team=self.team, distinct_id="id2")
        assert pdi_id1.person_id == person.id
        assert pdi_id2.person_id != person.id

    def test_split_with_max_splits(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(
            ["id1", "id2", "id3", "id4"], mock_create_pdi, mock_create_person
        )

        person.split_person(main_distinct_id="id1", max_splits=2)

        pdi_id1 = PersonDistinctId.objects.get(team=self.team, distinct_id="id1")
        pdi_id2 = PersonDistinctId.objects.get(team=self.team, distinct_id="id2")
        pdi_id3 = PersonDistinctId.objects.get(team=self.team, distinct_id="id3")
        pdi_id4 = PersonDistinctId.objects.get(team=self.team, distinct_id="id4")

        assert pdi_id1.person_id == person.id
        assert pdi_id2.person_id == person.id
        assert pdi_id3.person_id != person.id
        assert pdi_id4.person_id != person.id

    def test_split_single_distinct_id_is_noop(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(["only_id"], mock_create_pdi, mock_create_person)

        person.split_person(main_distinct_id="only_id")

        pdi = PersonDistinctId.objects.get(team=self.team, distinct_id="only_id")
        assert pdi.person_id == person.id
        mock_create_pdi.assert_not_called()
        mock_create_person.assert_not_called()

    def test_split_sets_correct_person_version(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(["id1", "id2"], mock_create_pdi, mock_create_person, version=5)

        person.split_person(main_distinct_id="id1")

        pdi_id2 = PersonDistinctId.objects.get(team=self.team, distinct_id="id2")
        new_person = Person.objects.get(team_id=self.team.id, id=pdi_id2.person_id)

        assert new_person.version == 5 + 101

    def test_split_sets_correct_pdi_version(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(["id1", "id2"], mock_create_pdi, mock_create_person)
        pdi = PersonDistinctId.objects.get(team=self.team, distinct_id="id2")
        pdi.version = 3
        pdi.save()
        mock_create_pdi.reset_mock()

        person.split_person(main_distinct_id="id1")

        pdi.refresh_from_db()
        assert pdi.version == 3 + 101

    def test_split_creates_deterministic_uuids(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(["id1", "id2"], mock_create_pdi, mock_create_person)

        person.split_person(main_distinct_id="id1")

        pdi_id2 = PersonDistinctId.objects.get(team=self.team, distinct_id="id2")
        new_person = Person.objects.get(team_id=self.team.id, id=pdi_id2.person_id)

        expected_uuid = uuidFromDistinctId(self.team.id, "id2")
        assert new_person.uuid == expected_uuid

    def test_split_publishes_correct_kafka_messages(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(["id1", "id2", "id3"], mock_create_pdi, mock_create_person)

        person.split_person(main_distinct_id="id1")

        assert mock_create_pdi.call_count == 2
        assert mock_create_person.call_count == 2

        kafka_pdi_distinct_ids = {call.kwargs["distinct_id"] for call in mock_create_pdi.call_args_list}
        assert kafka_pdi_distinct_ids == {"id2", "id3"}

        for call in mock_create_pdi.call_args_list:
            assert call.kwargs["team_id"] == self.team.id
            assert call.kwargs["is_deleted"] is False

        for call in mock_create_person.call_args_list:
            assert call.kwargs["team_id"] == self.team.id

    def test_split_rolls_back_on_failure(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(["id1", "id2", "id3"], mock_create_pdi, mock_create_person)

        original_pdi_ids = {
            did: PersonDistinctId.objects.get(team=self.team, distinct_id=did).person_id
            for did in ["id1", "id2", "id3"]
        }
        original_person_count = Person.objects.filter(team_id=self.team.id).count()

        with patch.object(PersonDistinctId.objects, "bulk_update", side_effect=Exception("simulated failure")):
            with self.assertRaises(Exception, msg="simulated failure"):
                person.split_person(main_distinct_id="id1")

        # All PDIs should still point to the original person
        for did in ["id1", "id2", "id3"]:
            pdi = PersonDistinctId.objects.get(team=self.team, distinct_id=did)
            assert pdi.person_id == original_pdi_ids[did]

        # No new persons should have been committed
        assert Person.objects.filter(team_id=self.team.id).count() == original_person_count

    def test_split_updates_version_on_pre_existing_person(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(["id1", "id2"], mock_create_pdi, mock_create_person, version=5)

        # Pre-create a person with the UUID that split would generate, simulating a previous partial run
        expected_uuid = uuidFromDistinctId(self.team.id, "id2")
        pre_existing = Person.objects.create(
            team=self.team,
            uuid=expected_uuid,
            version=0,
        )
        mock_create_person.reset_mock()
        mock_create_pdi.reset_mock()

        person.split_person(main_distinct_id="id1")

        # The pre-existing person's version should be updated to original_version + 101
        pre_existing.refresh_from_db()
        assert pre_existing.version == 5 + 101

        # PDI should point to the pre-existing person
        pdi_id2 = PersonDistinctId.objects.get(team=self.team, distinct_id="id2")
        assert pdi_id2.person_id == pre_existing.id

        # Kafka message should carry the updated version
        person_calls = [c for c in mock_create_person.call_args_list if c.kwargs.get("uuid") == str(expected_uuid)]
        assert len(person_calls) == 1
        assert person_calls[0].kwargs["version"] == 5 + 101

    def test_partial_split_moves_only_specified_distinct_ids(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(
            ["keep1", "move1", "keep2", "move2", "keep3"],
            mock_create_pdi,
            mock_create_person,
            properties={"email": "mega@example.com", "name": "Mega"},
        )

        person.split_person(main_distinct_id=None, distinct_ids_to_split=["move1", "move2"])

        # Original person keeps its properties intact — this is the key partial-split guarantee.
        person.refresh_from_db()
        assert person.properties == {"email": "mega@example.com", "name": "Mega"}

        # Kept distinct_ids remain on the original person.
        for did in ["keep1", "keep2", "keep3"]:
            pdi = PersonDistinctId.objects.get(team=self.team, distinct_id=did)
            assert pdi.person_id == person.id

        # Moved distinct_ids each land on their own new person.
        pdi_move1 = PersonDistinctId.objects.get(team=self.team, distinct_id="move1")
        pdi_move2 = PersonDistinctId.objects.get(team=self.team, distinct_id="move2")
        assert pdi_move1.person_id != person.id
        assert pdi_move2.person_id != person.id
        assert pdi_move1.person_id != pdi_move2.person_id

        assert mock_create_pdi.call_count == 2
        assert mock_create_person.call_count == 2

    def test_partial_split_rejects_unknown_distinct_id(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(["id1", "id2"], mock_create_pdi, mock_create_person)

        with self.assertRaises(ValueError):
            person.split_person(main_distinct_id=None, distinct_ids_to_split=["id1", "not_on_this_person"])

        # Nothing should have moved.
        for did in ["id1", "id2"]:
            pdi = PersonDistinctId.objects.get(team=self.team, distinct_id=did)
            assert pdi.person_id == person.id
        mock_create_pdi.assert_not_called()
        mock_create_person.assert_not_called()

    def test_partial_split_ignores_main_distinct_id_and_max_splits(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(
            ["a", "b", "c", "d"],
            mock_create_pdi,
            mock_create_person,
            properties={"email": "kept@example.com"},
        )

        # main_distinct_id and max_splits should both be ignored when the explicit list is given.
        person.split_person(main_distinct_id="a", max_splits=1, distinct_ids_to_split=["b", "c"])

        person.refresh_from_db()
        assert person.properties == {"email": "kept@example.com"}

        assert PersonDistinctId.objects.get(team=self.team, distinct_id="a").person_id == person.id
        assert PersonDistinctId.objects.get(team=self.team, distinct_id="d").person_id == person.id
        assert PersonDistinctId.objects.get(team=self.team, distinct_id="b").person_id != person.id
        assert PersonDistinctId.objects.get(team=self.team, distinct_id="c").person_id != person.id

    def test_partial_split_empty_list_is_noop(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(
            ["id1", "id2"],
            mock_create_pdi,
            mock_create_person,
            properties={"email": "noop@example.com"},
        )

        person.split_person(main_distinct_id=None, distinct_ids_to_split=[])

        person.refresh_from_db()
        assert person.properties == {"email": "noop@example.com"}
        for did in ["id1", "id2"]:
            assert PersonDistinctId.objects.get(team=self.team, distinct_id=did).person_id == person.id
        mock_create_pdi.assert_not_called()
        mock_create_person.assert_not_called()

    def test_partial_split_dedupes_duplicates(self, mock_create_pdi, mock_create_person):
        person = self._create_person_with_distinct_ids(["id1", "id2"], mock_create_pdi, mock_create_person)

        person.split_person(main_distinct_id=None, distinct_ids_to_split=["id2", "id2"])

        assert PersonDistinctId.objects.get(team=self.team, distinct_id="id1").person_id == person.id
        assert PersonDistinctId.objects.get(team=self.team, distinct_id="id2").person_id != person.id
        assert mock_create_pdi.call_count == 1
        assert mock_create_person.call_count == 1

    def test_split_many_distinct_ids(self, mock_create_pdi, mock_create_person):
        distinct_ids = ["main"] + [f"id_{i}" for i in range(100)]
        person = self._create_person_with_distinct_ids(distinct_ids, mock_create_pdi, mock_create_person)

        person.split_person(main_distinct_id="main")

        pdi_main = PersonDistinctId.objects.get(team=self.team, distinct_id="main")
        assert pdi_main.person_id == person.id

        split_person_ids = set()
        for i in range(100):
            pdi = PersonDistinctId.objects.get(team=self.team, distinct_id=f"id_{i}")
            assert pdi.person_id != person.id
            split_person_ids.add(pdi.person_id)

        assert len(split_person_ids) == 100

        assert mock_create_pdi.call_count == 100
        assert mock_create_person.call_count == 100
