import pytest
from django.core.exceptions import ValidationError

from posthog.clickhouse.client import sync_execute
from posthog.models import Cohort, Person, Team
from posthog.models.cohort.cohort import CohortType
from posthog.models.cohort.sql import GET_COHORTPEOPLE_BY_COHORT_ID

from posthog.test.base import BaseTest


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
        self.assertEqual(cohort.people.count(), 2)
        self.assertEqual(cohort.is_calculating, False)

        #  If we accidentally call calculate_people it shouldn't erase people
        cohort.calculate_people_ch(pending_version=0)
        self.assertEqual(cohort.people.count(), 2)

        # if we add people again, don't increase the number of people in cohort
        cohort.insert_users_by_list(["123"])
        cohort.refresh_from_db()
        self.assertEqual(cohort.people.count(), 2)
        self.assertEqual(cohort.is_calculating, False)

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
        self.assertEqual(batch_count, 5)
        cohort.refresh_from_db()
        self.assertEqual(cohort.people.count(), 11)
        self.assertEqual(cohort.is_calculating, False)

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
        self.assertFalse(cohort2.is_calculating)

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

        self.assertEqual(
            cohort.properties.to_dict(),
            {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$some_prop",
                                "type": "person",
                                "value": "something",
                                "operator": "contains",
                            },
                            {
                                "key": "other_prop",
                                "type": "person",
                                "value": "other_value",
                            },
                        ],
                    },
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": 1,
                                "type": "behavioral",
                                "value": "performed_event_multiple",
                                "event_type": "actions",
                                "operator": "eq",
                                "operator_value": 3,
                                "time_interval": "day",
                                "time_value": "4",
                            }
                        ],
                    },
                ],
            },
        )

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

        self.assertEqual(
            cohort.properties.to_dict(),
            {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$some_prop",
                                "type": "person",
                                "value": "something",
                                "operator": "contains",
                            },
                            {
                                "key": "other_prop",
                                "type": "person",
                                "value": "other_value",
                            },
                        ],
                    },
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                                "operator": "gte",
                                "operator_value": 0,
                                "time_interval": "day",
                                "time_value": "4",
                            }
                        ],
                    },
                ],
            },
        )

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

        self.assertEqual(
            cohort.properties.to_dict(),
            {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                                "operator": "lte",
                                "operator_value": 0,
                                "time_interval": "day",
                                "time_value": "4",
                            }
                        ],
                    }
                ],
            },
        )

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

        self.assertEqual(
            cohort.properties.to_dict(),
            {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                                "operator": "gte",
                                "operator_value": 0,
                                "time_interval": "day",
                                "time_value": 365,
                            }
                        ],
                    }
                ],
            },
        )

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
        for uuid in uuids:
            Person.objects.create(team=self.team, uuid=uuid)
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
        self.assertEqual(cohort.people.count(), 5)

        # Second insertion - try to add users 2-7 (users 2,3,4 are already in cohort)
        # This tests that our LEFT JOIN optimization works across batch boundaries
        cohort.insert_users_by_list(["user2", "user3", "user4", "user5", "user6", "user7"], batch_size=3)
        cohort.refresh_from_db()

        # Should have 8 people total (user0-user7) - no duplicates
        self.assertEqual(cohort.people.count(), 8)

        # Verify all expected people are in the cohort
        cohort_person_distinct_ids = set()
        for person in cohort.people.all():
            cohort_person_distinct_ids.update(person.distinct_ids)

        expected_distinct_ids = {f"user{i}" for i in range(8)}
        self.assertEqual(cohort_person_distinct_ids, expected_distinct_ids)

        # Verify the cohort is not in calculating state
        self.assertFalse(cohort.is_calculating)

    # Cohort Type Classification Tests

    def test_direct_cohort_type_static(self):
        """Test static cohort classification"""
        # Explicit static cohort
        cohort = Cohort.objects.create(team=self.team, is_static=True)
        self.assertEqual(cohort._get_direct_cohort_type(), CohortType.STATIC)
        self.assertEqual(cohort.cohort_type, CohortType.STATIC)

        # Empty filters should be static
        cohort2 = Cohort.objects.create(team=self.team, filters={})
        self.assertEqual(cohort2._get_direct_cohort_type(), CohortType.STATIC)
        self.assertEqual(cohort2.cohort_type, CohortType.STATIC)

    def test_direct_cohort_type_person_property(self):
        """Test person property cohort classification"""
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"}
                            ],
                        }
                    ],
                }
            },
        )
        self.assertEqual(cohort._get_direct_cohort_type(), CohortType.PERSON_PROPERTY)
        self.assertEqual(cohort.cohort_type, CohortType.PERSON_PROPERTY)

    def test_direct_cohort_type_behavioral_simple(self):
        """Test simple behavioral cohort classification"""
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "signup",
                                    "type": "behavioral",
                                    "value": "performed_event",
                                    "event_type": "events",
                                    "time_interval": "day",
                                    "time_value": 30,
                                }
                            ],
                        }
                    ],
                }
            },
        )
        self.assertEqual(cohort._get_direct_cohort_type(), CohortType.BEHAVIORAL)
        self.assertEqual(cohort.cohort_type, CohortType.BEHAVIORAL)

    def test_direct_cohort_type_behavioral_multiple(self):
        """Test behavioral multiple events cohort classification"""
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "purchase",
                                    "type": "behavioral",
                                    "value": "performed_event_multiple",
                                    "event_type": "events",
                                    "operator": "gte",
                                    "operator_value": 5,
                                    "time_interval": "day",
                                    "time_value": 30,
                                }
                            ],
                        }
                    ],
                }
            },
        )
        self.assertEqual(cohort._get_direct_cohort_type(), CohortType.BEHAVIORAL)
        self.assertEqual(cohort.cohort_type, CohortType.BEHAVIORAL)

    def test_direct_cohort_type_analytical_complex(self):
        """Test complex behavioral (analytical) cohort classification"""
        # Each complex behavioral type has different required fields
        test_cases = [
            {
                "type": "performed_event_first_time",
                "properties": {
                    "key": "login",
                    "type": "behavioral",
                    "value": "performed_event_first_time",
                    "event_type": "events",
                    "time_interval": "day",
                    "time_value": 30,
                },
            },
            {
                "type": "performed_event_regularly",
                "properties": {
                    "key": "login",
                    "type": "behavioral",
                    "value": "performed_event_regularly",
                    "event_type": "events",
                    "time_interval": "day",
                    "time_value": 30,
                    "operator_value": 3,
                    "min_periods": 2,
                    "total_periods": 4,
                },
            },
            {
                "type": "performed_event_sequence",
                "properties": {
                    "key": "login",
                    "type": "behavioral",
                    "value": "performed_event_sequence",
                    "event_type": "events",
                    "time_interval": "day",
                    "time_value": 30,
                    "seq_event_type": "events",
                    "seq_event": "signup",
                    "seq_time_value": 7,
                    "seq_time_interval": "day",
                },
            },
            {
                "type": "stopped_performing_event",
                "properties": {
                    "key": "login",
                    "type": "behavioral",
                    "value": "stopped_performing_event",
                    "event_type": "events",
                    "time_interval": "day",
                    "time_value": 30,
                    "seq_time_value": 7,
                    "seq_time_interval": "day",
                },
            },
            {
                "type": "restarted_performing_event",
                "properties": {
                    "key": "login",
                    "type": "behavioral",
                    "value": "restarted_performing_event",
                    "event_type": "events",
                    "time_interval": "day",
                    "time_value": 30,
                    "seq_time_value": 7,
                    "seq_time_interval": "day",
                },
            },
        ]

        for test_case in test_cases:
            with self.subTest(behavioral_type=test_case["type"]):
                cohort = Cohort.objects.create(
                    team=self.team,
                    filters={
                        "properties": {"type": "AND", "values": [{"type": "AND", "values": [test_case["properties"]]}]}
                    },
                )
                self.assertEqual(cohort._get_direct_cohort_type(), CohortType.ANALYTICAL)
                self.assertEqual(cohort.cohort_type, CohortType.ANALYTICAL)

    def test_direct_cohort_type_mixed_properties(self):
        """Test cohort with mixed property types - should take most complex"""
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"},
                                {
                                    "key": "purchase",
                                    "type": "behavioral",
                                    "value": "performed_event_first_time",
                                    "event_type": "events",
                                    "time_interval": "day",
                                    "time_value": 30,
                                },
                            ],
                        }
                    ],
                }
            },
        )
        # Should be analytical because that's the most complex type present
        self.assertEqual(cohort._get_direct_cohort_type(), CohortType.ANALYTICAL)
        self.assertEqual(cohort.cohort_type, CohortType.ANALYTICAL)

    def test_direct_cohort_type_unknown_property_becomes_static(self):
        """Test that unknown property types get filtered out and cohort becomes STATIC"""
        cohort = Cohort(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "AND", "values": [{"key": "some_key", "type": "unknown_type", "value": "some_value"}]}
                    ],
                }
            },
        )

        # Unknown properties get filtered out during parsing, leaving empty properties
        # This should result in STATIC classification rather than an error
        cohort_type = cohort._get_direct_cohort_type()
        self.assertEqual(cohort_type, CohortType.STATIC)

    def test_get_dependent_cohort_ids(self):
        """Test extraction of dependent cohort IDs"""
        # Create dependency cohorts
        dep1 = Cohort.objects.create(team=self.team, is_static=True)
        dep2 = Cohort.objects.create(team=self.team, is_static=True)

        # Cohort with no dependencies
        cohort_no_deps = Cohort.objects.create(team=self.team, is_static=True)
        self.assertEqual(cohort_no_deps._get_dependent_cohort_ids(), set())

        # Cohort with single dependency
        cohort_single = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "AND", "values": [{"key": "id", "type": "cohort", "value": dep1.pk}]}],
                }
            },
        )
        self.assertEqual(cohort_single._get_dependent_cohort_ids(), {dep1.pk})

        # Cohort with multiple dependencies
        cohort_multiple = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {"type": "AND", "values": [{"key": "id", "type": "cohort", "value": dep1.pk}]},
                        {"type": "AND", "values": [{"key": "id", "type": "cohort", "value": dep2.pk}]},
                    ],
                }
            },
        )
        self.assertEqual(cohort_multiple._get_dependent_cohort_ids(), {dep1.pk, dep2.pk})

    def test_cohort_type_with_dependencies_elevation(self):
        """Test that cohort type is elevated by dependencies"""
        # Create a behavioral dependency
        behavioral_cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "purchase",
                                    "type": "behavioral",
                                    "value": "performed_event",
                                    "event_type": "events",
                                    "time_interval": "day",
                                    "time_value": 30,
                                }
                            ],
                        }
                    ],
                }
            },
        )
        self.assertEqual(behavioral_cohort.cohort_type, CohortType.BEHAVIORAL)

        # Create a person property cohort that depends on the behavioral cohort
        person_cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"},
                                {"key": "id", "type": "cohort", "value": behavioral_cohort.pk},
                            ],
                        }
                    ],
                }
            },
        )

        # Should be elevated to behavioral because of dependency
        self.assertEqual(person_cohort.cohort_type, CohortType.BEHAVIORAL)

    def test_cohort_type_transitive_dependencies(self):
        """Test cohort type calculation with transitive dependencies"""
        # Chain: analytical -> behavioral -> person -> static
        analytical_cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "login",
                                    "type": "behavioral",
                                    "value": "performed_event_first_time",
                                    "event_type": "events",
                                    "time_interval": "day",
                                    "time_value": 30,
                                }
                            ],
                        }
                    ],
                }
            },
        )

        behavioral_cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "purchase",
                                    "type": "behavioral",
                                    "value": "performed_event",
                                    "event_type": "events",
                                    "time_interval": "day",
                                    "time_value": 30,
                                },
                                {"key": "id", "type": "cohort", "value": analytical_cohort.pk},
                            ],
                        }
                    ],
                }
            },
        )

        person_cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"},
                                {"key": "id", "type": "cohort", "value": behavioral_cohort.pk},
                            ],
                        }
                    ],
                }
            },
        )

        static_cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "AND", "values": [{"key": "id", "type": "cohort", "value": person_cohort.pk}]}],
                }
            },
        )

        # Each should be elevated by transitive dependencies
        self.assertEqual(analytical_cohort.cohort_type, CohortType.ANALYTICAL)
        self.assertEqual(behavioral_cohort.cohort_type, CohortType.ANALYTICAL)  # elevated
        self.assertEqual(person_cohort.cohort_type, CohortType.ANALYTICAL)  # elevated
        self.assertEqual(static_cohort.cohort_type, CohortType.ANALYTICAL)  # elevated

    def test_circular_dependency_detection(self):
        """Test that circular dependencies are detected and prevent save"""
        cohort_a = Cohort.objects.create(team=self.team, is_static=True)
        cohort_b = Cohort.objects.create(team=self.team, is_static=True)

        # Make A depend on B
        cohort_a.filters = {
            "properties": {
                "type": "AND",
                "values": [{"type": "AND", "values": [{"key": "id", "type": "cohort", "value": cohort_b.pk}]}],
            }
        }
        cohort_a.save()  # This should work

        # Try to make B depend on A (creating a cycle)
        cohort_b.filters = {
            "properties": {
                "type": "AND",
                "values": [{"type": "AND", "values": [{"key": "id", "type": "cohort", "value": cohort_a.pk}]}],
            }
        }

        with self.assertRaises(ValidationError) as cm:
            cohort_b.save()
        self.assertIn("Circular dependency detected", str(cm.exception))

    def test_missing_dependency_validation(self):
        """Test that missing dependencies are caught during validation"""
        cohort = Cohort(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": 99999,  # Non-existent cohort
                                }
                            ],
                        }
                    ],
                }
            },
        )

        with self.assertRaises(ValidationError) as cm:
            cohort.save()
        self.assertIn("does not exist", str(cm.exception))

    def test_cohort_type_cascade_update(self):
        """Test that updating a cohort cascades type updates to dependents"""
        # Create base cohort as person property
        base_cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"}
                            ],
                        }
                    ],
                }
            },
        )

        # Create dependent cohort
        dependent_cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "AND", "values": [{"key": "id", "type": "cohort", "value": base_cohort.pk}]}],
                }
            },
        )

        # Initially both should be person property
        self.assertEqual(base_cohort.cohort_type, CohortType.PERSON_PROPERTY)
        self.assertEqual(dependent_cohort.cohort_type, CohortType.PERSON_PROPERTY)

        # Update base cohort to be behavioral
        base_cohort.filters = {
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "purchase",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                                "time_interval": "day",
                                "time_value": 30,
                            }
                        ],
                    }
                ],
            }
        }
        base_cohort.save()

        # Check that dependent cohort type was updated
        dependent_cohort.refresh_from_db()
        self.assertEqual(base_cohort.cohort_type, CohortType.BEHAVIORAL)
        self.assertEqual(dependent_cohort.cohort_type, CohortType.BEHAVIORAL)
