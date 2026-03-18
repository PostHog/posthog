from posthog.test.base import BaseTest

from posthog.management.commands.delete_persons import delete_persons_batch
from posthog.models import Person, Team


class TestDeletePersonsBatch(BaseTest):
    """
    Tests that verify the delete_persons_batch function deletes the correct persons.
    """

    def setUp(self):
        super().setUp()
        self.person1 = Person.objects.create(team=self.team, properties={"name": "person1"})
        self.person2 = Person.objects.create(team=self.team, properties={"name": "person2"})
        self.person3 = Person.objects.create(team=self.team, properties={"name": "person3"})

        self.other_team = Team.objects.create(organization=self.organization, name="Other Team")
        self.other_person = Person.objects.create(team=self.other_team, properties={"name": "other"})

    def get_remaining_person_ids(self) -> set[int]:
        return set(Person.objects.filter(team=self.team).values_list("id", flat=True))

    def test_deletes_all_persons_for_team_when_no_filter(self):
        """When person_ids is empty list, delete ALL persons for the team."""
        result = delete_persons_batch(team_id=self.team.id, person_ids=[], batch_size=1000)

        assert result.persons_deleted == 3
        assert self.get_remaining_person_ids() == set()
        assert Person.objects.filter(id=self.other_person.id).exists()

    def test_deletes_only_specified_persons_when_filtered(self):
        """When person_ids is provided, delete only those persons."""
        result = delete_persons_batch(
            team_id=self.team.id,
            person_ids=[self.person1.id, self.person3.id],
            batch_size=1000,
        )

        assert result.persons_deleted == 2
        assert self.get_remaining_person_ids() == {self.person2.id}

    def test_deletes_single_person(self):
        """When a single person_id is provided, delete only that person."""
        result = delete_persons_batch(
            team_id=self.team.id,
            person_ids=[self.person2.id],
            batch_size=1000,
        )

        assert result.persons_deleted == 1
        assert self.get_remaining_person_ids() == {self.person1.id, self.person3.id}

    def test_deletes_nothing_when_person_ids_dont_exist(self):
        """When person_ids don't exist in team, delete nothing."""
        result = delete_persons_batch(
            team_id=self.team.id,
            person_ids=[999999, 999998],
            batch_size=1000,
        )

        assert result.persons_deleted == 0
        assert self.get_remaining_person_ids() == {self.person1.id, self.person2.id, self.person3.id}

    def test_deletes_nothing_when_person_ids_belong_to_other_team(self):
        """When person_ids belong to another team, delete nothing."""
        result = delete_persons_batch(
            team_id=self.team.id,
            person_ids=[self.other_person.id],
            batch_size=1000,
        )

        assert result.persons_deleted == 0
        assert self.get_remaining_person_ids() == {self.person1.id, self.person2.id, self.person3.id}
        assert Person.objects.filter(id=self.other_person.id).exists()

    def test_respects_batch_size_limit(self):
        """Batch size limits how many persons are deleted in one call."""
        result = delete_persons_batch(
            team_id=self.team.id,
            person_ids=[],
            batch_size=2,
        )

        assert result.persons_deleted == 2
        assert len(self.get_remaining_person_ids()) == 1
