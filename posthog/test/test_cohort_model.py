import uuid

import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models import Cohort, Person, Team
from posthog.models.cohort.sql import GET_COHORTPEOPLE_BY_COHORT_ID
from posthog.models.property_definition import PropertyDefinition, PropertyType


class TestCohort(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False  # So that each test gets a different team_id, ensuring separation of CH data

    def test_insert_by_distinct_id(self):
        Person.objects.create(team=self.team, distinct_ids=["000"])
        Person.objects.create(team=self.team, distinct_ids=["123"])
        Person.objects.create(team=self.team)
        # Team leakage
        team2 = Team.objects.create(organization=self.organization)
        Person.objects.create(team=team2, distinct_ids=["123"])

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)
        cohort.insert_users_by_list(["a header or something", "123", "000", "email@example.org"])
        cohort.refresh_from_db()
        assert cohort.people.count() == 2
        assert cohort.is_calculating == False

        #  If we accidentally call calculate_people it shouldn't erase people
        cohort.calculate_people_ch(pending_version=0)
        assert cohort.people.count() == 2

        # if we add people again, don't increase the number of people in cohort
        cohort.insert_users_by_list(["123"])
        cohort.refresh_from_db()
        assert cohort.people.count() == 2
        assert cohort.is_calculating == False

    def test_insert_by_distinct_id_in_batches(self):
        Person.objects.create(team=self.team, distinct_ids=["000"])
        Person.objects.create(team=self.team, distinct_ids=["001"])
        Person.objects.create(team=self.team, distinct_ids=["002", "011"])
        Person.objects.create(team=self.team, distinct_ids=["003", "012"])
        Person.objects.create(team=self.team, distinct_ids=["004"])
        Person.objects.create(team=self.team, distinct_ids=["005"])
        Person.objects.create(team=self.team, distinct_ids=["006"])
        Person.objects.create(team=self.team, distinct_ids=["007"])
        Person.objects.create(team=self.team, distinct_ids=["008"])
        Person.objects.create(team=self.team, distinct_ids=["009"])
        Person.objects.create(team=self.team, distinct_ids=["010"])

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)
        batch_count = cohort.insert_users_by_list(
            ["000", "001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012"], batch_size=3
        )
        assert batch_count == 5
        cohort.refresh_from_db()
        assert cohort.people.count() == 11
        assert cohort.is_calculating == False

    @pytest.mark.ee
    def test_calculating_cohort_clickhouse(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )
        person1 = Person.objects.create(
            distinct_ids=["person1"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        Person.objects.create(distinct_ids=["person2"], team_id=self.team.pk, properties={})
        person3 = Person.objects.create(
            distinct_ids=["person3"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        cohort.calculate_people_ch(pending_version=0)

        uuids = [
            row[0]
            for row in sync_execute(
                GET_COHORTPEOPLE_BY_COHORT_ID,
                {
                    "cohort_id": cohort.pk,
                    "team_id": self.team.pk,
                    "version": cohort.version,
                },
            )
        ]
        self.assertCountEqual(uuids, [person1.uuid, person3.uuid])

    def test_empty_query(self):
        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "nomatchihope", "type": "person"}]}],
            name="cohort1",
        )

        cohort2.calculate_people_ch(pending_version=0)
        cohort2.refresh_from_db()
        assert not cohort2.is_calculating

    def test_group_to_property_conversion(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "$some_prop",
                            "value": "something",
                            "type": "person",
                            "operator": "contains",
                        },
                        {"key": "other_prop", "value": "other_value", "type": "person"},
                    ]
                },
                {
                    "days": "4",
                    "count": "3",
                    "label": "$pageview",
                    "action_id": 1,
                    "count_operator": "eq",
                },
            ],
            name="cohort1",
        )

        assert cohort.properties.to_dict() == {"type": "OR", "values": [{"type": "AND", "values": [{"key": "$some_prop", "type": "person", "value": "something", "operator": "contains"}, {"key": "other_prop", "type": "person", "value": "other_value"}]}, {"type": "AND", "values": [{"key": 1, "type": "behavioral", "value": "performed_event_multiple", "event_type": "actions", "operator": "eq", "operator_value": 3, "time_interval": "day", "time_value": "4"}]}]}

    def test_group_to_property_conversion_with_valid_zero_count(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "$some_prop",
                            "value": "something",
                            "type": "person",
                            "operator": "contains",
                        },
                        {"key": "other_prop", "value": "other_value", "type": "person"},
                    ]
                },
                {
                    "days": "4",
                    "count": "0",
                    "label": "$pageview",
                    "event_id": "$pageview",
                    "count_operator": "gte",
                },
            ],
            name="cohort1",
        )

        assert cohort.properties.to_dict() == {"type": "OR", "values": [{"type": "AND", "values": [{"key": "$some_prop", "type": "person", "value": "something", "operator": "contains"}, {"key": "other_prop", "type": "person", "value": "other_value"}]}, {"type": "AND", "values": [{"key": "$pageview", "type": "behavioral", "value": "performed_event", "event_type": "events", "operator": "gte", "operator_value": 0, "time_interval": "day", "time_value": "4"}]}]}

    def test_group_to_property_conversion_with_valid_zero_count_different_operator(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "days": "4",
                    "count": "0",
                    "label": "$pageview",
                    "event_id": "$pageview",
                    "count_operator": "lte",
                }
            ],
            name="cohort1",
        )

        assert cohort.properties.to_dict() == {"type": "OR", "values": [{"type": "AND", "values": [{"key": "$pageview", "type": "behavioral", "value": "performed_event", "event_type": "events", "operator": "lte", "operator_value": 0, "time_interval": "day", "time_value": "4"}]}]}

    def test_group_to_property_conversion_with_missing_days_and_invalid_count(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "count": -3,
                    "label": "$pageview",
                    "event_id": "$pageview",
                    "count_operator": "gte",
                }
            ],
            name="cohort1",
        )

        assert cohort.properties.to_dict() == {"type": "OR", "values": [{"type": "AND", "values": [{"key": "$pageview", "type": "behavioral", "value": "performed_event", "event_type": "events", "operator": "gte", "operator_value": 0, "time_interval": "day", "time_value": 365}]}]}

    def test_insert_users_list_by_uuid(self):
        # These are some fine uuids.
        uuids = [
            "96757a52-a170-4cbb-ad49-a713c20b56e0",
            "74615ff4-1573-45b7-98ca-9897df0f8332",
            "0cbdd9c3-be93-4291-b721-2dbba2093f62",
            "243103c3-b41a-4c81-89d1-59c61f36244c",
            "85167c43-e611-4442-be3c-ede1e1788b6a",
            "8f926bdd-29e8-4b6f-8eda-053e9ef0c4ec",
            "8a3954b6-61f6-429f-ad8a-65db1e2728a9",
            "d2d26447-8700-422d-99ad-c37b5fb6602a",
            "0c386ba6-6307-460f-90b3-0f0ed0aee893",
            "fe3876bc-c75c-4c79-ae55-2af6892b9da7",
            "345b621a-26e1-4888-a9eb-175329f7923b",
        ]
        for person_uuid in uuids:
            Person.objects.create(team=self.team, uuid=person_uuid)
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)

        # Insert all users into the cohort using batching (batchsize=3)
        cohort.insert_users_list_by_uuid(items=uuids, team_id=self.team.id, batchsize=3)

        # Fetch all persons in the cohort
        cohort.refresh_from_db()
        # TODO: THIS NEXT ASSERT FAILS AND I DON'T KNOW WHY. WILL FIGURE OUT LATER - @haacked
        # assert cohort.count == 11
        assert cohort.people.count() == 11
        cohort_person_uuids = {str(p.uuid) for p in cohort.people.all()}
        assert cohort_person_uuids == set(uuids)
        assert cohort.is_calculating is False

    def test_insert_users_by_list_avoids_duplicates_with_batching(self):
        """Test that batching with duplicates works correctly - people already in cohort are not re-inserted."""
        # Create people with distinct IDs
        for i in range(10):
            Person.objects.create(team=self.team, distinct_ids=[f"user{i}"])

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)

        # First insertion - add users 0-4 (batch size 3 will create batches: [0,1,2], [3,4])
        cohort.insert_users_by_list(["user0", "user1", "user2", "user3", "user4"], batch_size=3)
        cohort.refresh_from_db()
        assert cohort.people.count() == 5

        # Second insertion - try to add users 2-7 (users 2,3,4 are already in cohort)
        # This tests that our LEFT JOIN optimization works across batch boundaries
        cohort.insert_users_by_list(["user2", "user3", "user4", "user5", "user6", "user7"], batch_size=3)
        cohort.refresh_from_db()

        # Should have 8 people total (user0-user7) - no duplicates
        assert cohort.people.count() == 8

        # Verify all expected people are in the cohort
        cohort_person_distinct_ids = set()
        for person in cohort.people.all():
            cohort_person_distinct_ids.update(person.distinct_ids)

        expected_distinct_ids = {f"user{i}" for i in range(8)}
        assert cohort_person_distinct_ids == expected_distinct_ids

        # Verify the cohort is not in calculating state
        assert not cohort.is_calculating

    @parameterized.expand(
        [
            # operator, filter_value, excluded_ages, included_ages
            ["between", [18, 65], [15, 70], [25, 35, 18, 65]],
            ["not_between", [18, 65], [25, 18, 65], [15, 70]],
            ["min", 18, [15], [18, 25]],
            ["max", 65, [70], [25, 65]],
        ]
    )
    def test_calculating_cohort_with_numeric_property_operators(
        self, operator, filter_value, excluded_ages, included_ages
    ):
        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.PERSON, name="age", property_type=PropertyType.Numeric
        )
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "age", "value": filter_value, "operator": operator, "type": "person"}]}],
            name="my_cohort",
        )

        for age in excluded_ages:
            Person.objects.create(
                distinct_ids=[str(uuid.uuid4())],
                team_id=self.team.pk,
                properties={"age": age},
            )

        expected_people = []
        for age in included_ages:
            person = Person.objects.create(
                distinct_ids=[str(uuid.uuid4())],
                team_id=self.team.pk,
                properties={"age": age},
            )
            expected_people.append(person)

        cohort.calculate_people_ch(pending_version=0)

        uuids = [
            row[0]
            for row in sync_execute(
                GET_COHORTPEOPLE_BY_COHORT_ID,
                {
                    "cohort_id": cohort.pk,
                    "team_id": self.team.pk,
                    "version": cohort.version,
                },
            )
        ]

        self.assertCountEqual(uuids, [p.uuid for p in expected_people])

    def test_get_static_cohort_size(self):
        """Test that get_static_cohort_size works with db_constraint=False on the person foreign key."""
        from posthog.models.cohort.util import get_static_cohort_size

        # Create persons
        person1 = Person.objects.create(team=self.team, distinct_ids=["person1"])
        person2 = Person.objects.create(team=self.team, distinct_ids=["person2"])
        person3 = Person.objects.create(team=self.team, distinct_ids=["person3"])

        # Create a static cohort
        cohort = Cohort.objects.create(team=self.team, name="Test Static Cohort", is_static=True)

        # Add persons to cohort using the many-to-many relationship
        cohort.people.add(person1, person2, person3)

        # Test that get_static_cohort_size returns the correct count
        size = get_static_cohort_size(cohort_id=cohort.id, team_id=self.team.id)

        # This should return 3, not a CombinedExpression
        assert isinstance(size, int), f"Expected int, got {type(size)}: {size}"
        assert size == 3, f"Expected 3 persons in cohort, got {size}"

        # Test with team leakage - person from another team should not be counted
        team2 = Team.objects.create(organization=self.organization)
        person4 = Person.objects.create(team=team2, distinct_ids=["person4"])
        cohort.people.add(person4)

        size = get_static_cohort_size(cohort_id=cohort.id, team_id=self.team.id)
        assert size == 3, f"Expected 3 persons from team {self.team.id}, got {size}"
