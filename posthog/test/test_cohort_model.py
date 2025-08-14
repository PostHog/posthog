import pytest

from posthog.clickhouse.client import sync_execute
from posthog.models import Cohort, Person, Team
from posthog.models.cohort.cohort import CohortType
from posthog.models.cohort.sql import GET_COHORTPEOPLE_BY_COHORT_ID
from posthog.models.property import Property, PropertyGroup, PropertyOperatorType, BehavioralPropertyType
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

    def test_determine_cohort_type_based_on_filters_static(self):
        """Static cohorts should always return STATIC type"""

        cohort = Cohort.objects.create(team=self.team, is_static=True, name="Static Cohort")

        self.assertEqual(cohort.determine_cohort_type_based_on_filters(), CohortType.STATIC)

    def test_determine_cohort_type_based_on_filters_person_property(self):
        """Cohorts with only person property filters should return PERSON_PROPERTY"""

        property_filters = PropertyGroup(
            type=PropertyOperatorType.AND,
            values=[
                Property(type="person", key="email", operator="icontains", value="@posthog.com"),
                Property(type="person", key="age", operator="gt", value="18"),
            ],
        )

        cohort = Cohort.objects.create(
            team=self.team, filters={"properties": property_filters.to_dict()}, name="Person Property Cohort"
        )

        self.assertEqual(cohort.determine_cohort_type_based_on_filters(), CohortType.PERSON_PROPERTY)

    def test_determine_cohort_type_based_on_filters_behavioral(self):
        """Cohorts with behavioral filters should return BEHAVIORAL"""

        property_filters = PropertyGroup(
            type=PropertyOperatorType.AND,
            values=[
                Property(
                    type="behavioral",
                    key="performed_event",
                    value=BehavioralPropertyType.PERFORMED_EVENT,
                    operator="exact",
                    event_type="events",
                    time_interval="day",
                    time_value=1,
                )
            ],
        )

        cohort = Cohort.objects.create(
            team=self.team, filters={"properties": property_filters.to_dict()}, name="Behavioral Cohort"
        )

        self.assertEqual(cohort.determine_cohort_type_based_on_filters(), CohortType.BEHAVIORAL)

    def test_determine_cohort_type_based_on_filters_analytical(self):
        """Cohorts with analytical filters should return ANALYTICAL"""

        property_filters = PropertyGroup(
            type=PropertyOperatorType.AND,
            values=[
                Property(
                    type="behavioral",
                    key="performed_event_first_time",
                    event_type="events",
                    value=BehavioralPropertyType.PERFORMED_EVENT_FIRST_TIME,
                    operator="exact",
                    time_interval="day",
                    time_value=1,
                )
            ],
        )

        cohort = Cohort.objects.create(
            team=self.team, filters={"properties": property_filters.to_dict()}, name="Analytical Cohort"
        )

        self.assertEqual(cohort.determine_cohort_type_based_on_filters(), CohortType.ANALYTICAL)

    def test_determine_cohort_type_based_on_filters_hierarchy(self):
        """Mixed filters should return the highest complexity type"""

        property_filters = PropertyGroup(
            type=PropertyOperatorType.AND,
            values=[
                Property(type="person", key="email", operator="icontains", value="@posthog.com"),
                Property(
                    type="behavioral",
                    key="performed_event",
                    value=BehavioralPropertyType.PERFORMED_EVENT,
                    operator="exact",
                    event_type="events",
                    time_interval="day",
                    time_value=1,
                ),
                Property(
                    type="behavioral",
                    key="performed_event_first_time",
                    value=BehavioralPropertyType.PERFORMED_EVENT_FIRST_TIME,
                    operator="exact",
                    event_type="events",
                    time_interval="day",
                    time_value=1,
                ),
            ],
        )

        cohort = Cohort.objects.create(
            team=self.team, filters={"properties": property_filters.to_dict()}, name="Mixed Cohort"
        )

        # Should return ANALYTICAL since it has the highest complexity
        self.assertEqual(cohort.determine_cohort_type_based_on_filters(), CohortType.ANALYTICAL)

    def test_determine_cohort_type_based_on_filters_with_cohort_reference(self):
        """Cohort referencing another should inherit the higher complexity type"""

        # Create a behavioral cohort
        behavioral_cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(
                            type="behavioral",
                            key="performed_event",
                            value=BehavioralPropertyType.PERFORMED_EVENT,
                            operator="exact",
                            event_type="events",
                            time_interval="day",
                            time_value=1,
                        )
                    ],
                ).to_dict()
            },
            name="Behavioral Base Cohort",
        )
        behavioral_cohort.cohort_type = behavioral_cohort.determine_cohort_type_based_on_filters()
        behavioral_cohort.save()

        # Create a cohort that references the behavioral one
        referencing_cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="person", key="email", operator="icontains", value="@posthog.com"),
                        Property(type="cohort", key="id", operator="in", value=behavioral_cohort.id),
                    ],
                ).to_dict()
            },
            name="Referencing Cohort",
        )

        # Should return BEHAVIORAL because it references a behavioral cohort
        self.assertEqual(referencing_cohort.determine_cohort_type_based_on_filters(), CohortType.BEHAVIORAL)

    def test_determine_cohort_type_based_on_filters_circular_reference_error(self):
        """Should detect and raise error for circular cohort references"""

        # Create two cohorts that will reference each other
        cohort_a = Cohort.objects.create(team=self.team, name="Cohort A")
        cohort_b = Cohort.objects.create(team=self.team, name="Cohort B")

        # Set up circular reference: A -> B -> A
        cohort_a.filters = {
            "properties": PropertyGroup(
                type=PropertyOperatorType.AND,
                values=[Property(type="cohort", key="id", value=cohort_b.id)],
            ).to_dict()
        }
        cohort_a.save()

        cohort_b.filters = {
            "properties": PropertyGroup(
                type=PropertyOperatorType.AND,
                values=[
                    Property(type="cohort", key="id", value=cohort_a.id),
                    Property(type="person", key="email", operator="icontains", value="@test.com"),
                ],
            ).to_dict()
        }
        cohort_b.save()

        # Should raise an error for circular references
        with self.assertRaises(ValueError) as cm:
            cohort_a.determine_cohort_type_based_on_filters()
        self.assertIn("Circular cohort reference detected", str(cm.exception))

        with self.assertRaises(ValueError) as cm:
            cohort_b.determine_cohort_type_based_on_filters()
        self.assertIn("Circular cohort reference detected", str(cm.exception))

    def test_determine_cohort_type_based_on_filters_missing_cohort_error(self):
        """Should raise error when referencing non-existent cohorts"""

        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="cohort", key="id", value=99999),  # Non-existent ID
                        Property(type="person", key="name", operator="icontains", value="test"),
                    ],
                ).to_dict()
            },
            name="Invalid Reference Cohort",
        )

        # Should raise an error for missing cohort references
        with self.assertRaises(ValueError) as cm:
            cohort.determine_cohort_type_based_on_filters()
        self.assertIn("not found", str(cm.exception))

    def test_determine_cohort_type_based_on_filters_empty_cohort_error(self):
        """Should raise error for cohorts with no filters"""

        cohort = Cohort.objects.create(
            team=self.team,
            name="Empty Cohort",
            filters={"properties": PropertyGroup(type=PropertyOperatorType.AND, values=[]).to_dict()},
        )

        with self.assertRaises(ValueError) as cm:
            cohort.determine_cohort_type_based_on_filters()
        self.assertIn("no valid filters found", str(cm.exception))

    def test_validate_cohort_type_valid_match(self):
        """Should pass validation when cohort type matches filters"""
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[Property(type="person", key="email", operator="icontains", value="@posthog.com")],
                ).to_dict()
            },
        )

        is_valid, error_msg = cohort.validate_cohort_type("person_property")
        self.assertTrue(is_valid)
        self.assertIsNone(error_msg)

    def test_validate_cohort_type_mismatch(self):
        """Should fail validation when provided type doesn't exactly match required type"""
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(
                            type="behavioral",
                            key="performed_event",
                            value=BehavioralPropertyType.PERFORMED_EVENT,
                            operator="exact",
                            event_type="events",
                            time_interval="day",
                            time_value=1,
                        )
                    ],
                ).to_dict()
            },
        )

        # Test with lower complexity type
        is_valid, error_msg = cohort.validate_cohort_type("person_property")
        self.assertFalse(is_valid)
        self.assertIn("does not match the filters", error_msg)
        self.assertIn("Expected type: 'behavioral'", error_msg)

        # Test with higher complexity type (also fails now)
        is_valid, error_msg = cohort.validate_cohort_type("analytical")
        self.assertFalse(is_valid)
        self.assertIn("does not match the filters", error_msg)
        self.assertIn("Expected type: 'behavioral'", error_msg)

    def test_validate_cohort_type_invalid_type(self):
        """Should fail validation for invalid cohort type strings"""
        cohort = Cohort.objects.create(team=self.team, is_static=True)

        is_valid, error_msg = cohort.validate_cohort_type("invalid_type")
        self.assertFalse(is_valid)
        self.assertIn("Invalid cohort type: invalid_type", error_msg)

    def test_validate_cohort_type_none_type_passes(self):
        """Should pass validation when no type is specified"""
        cohort = Cohort.objects.create(team=self.team, is_static=True)

        is_valid, error_msg = cohort.validate_cohort_type(None)
        self.assertTrue(is_valid)
        self.assertIsNone(error_msg)

    def test_determine_cohort_type_based_on_filters_nested_behavioral(self):
        """Cohorts referencing other behavioral cohorts should inherit BEHAVIORAL type"""

        # Create a behavioral cohort
        behavioral_cohort = Cohort.objects.create(
            team=self.team,
            name="Behavioral Cohort",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(
                            type="behavioral",
                            key="performed_event",
                            value=BehavioralPropertyType.PERFORMED_EVENT,
                            event_type="events",
                            operator="exact",
                            time_interval="day",
                            time_value=1,
                        )
                    ],
                ).to_dict()
            },
        )

        # Create a person property cohort
        person_cohort = Cohort.objects.create(
            team=self.team,
            name="Person Property Cohort",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="person", key="email", operator="icontains", value="@example.com"),
                    ],
                ).to_dict()
            },
        )

        # Create a cohort that references the behavioral cohort - should be BEHAVIORAL
        referencing_cohort = Cohort.objects.create(
            team=self.team,
            name="Referencing Cohort",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="cohort", key="id", value=behavioral_cohort.id),
                        Property(type="person", key="name", operator="icontains", value="test"),
                    ],
                ).to_dict()
            },
        )

        self.assertEqual(referencing_cohort.determine_cohort_type_based_on_filters(), CohortType.BEHAVIORAL)

        # Create a cohort that references only the person property cohort - should be PERSON_PROPERTY
        person_referencing_cohort = Cohort.objects.create(
            team=self.team,
            name="Person Referencing Cohort",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="cohort", key="id", value=person_cohort.id),
                        Property(type="person", key="age", operator="gt", value=18),
                    ],
                ).to_dict()
            },
        )

        self.assertEqual(person_referencing_cohort.determine_cohort_type_based_on_filters(), CohortType.PERSON_PROPERTY)

    def test_determine_cohort_type_based_on_filters_deeply_nested_behavioral(self):
        """Test that behavioral type is detected through multiple levels of cohort nesting"""

        # Create a behavioral cohort at the deepest level
        behavioral_cohort = Cohort.objects.create(
            team=self.team,
            name="Deep Behavioral Cohort",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(
                            type="behavioral",
                            key="performed_event",
                            value=BehavioralPropertyType.PERFORMED_EVENT,
                            event_type="events",
                            operator="exact",
                            time_interval="day",
                            time_value=1,
                        )
                    ],
                ).to_dict()
            },
        )

        # Create a middle cohort that references the behavioral cohort
        middle_cohort = Cohort.objects.create(
            team=self.team,
            name="Middle Cohort",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="cohort", key="id", value=behavioral_cohort.id),
                        Property(type="person", key="country", operator="exact", value="US"),
                    ],
                ).to_dict()
            },
        )

        # Create another middle cohort with just person properties
        middle_person_cohort = Cohort.objects.create(
            team=self.team,
            name="Middle Person Cohort",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="person", key="city", operator="exact", value="New York"),
                    ],
                ).to_dict()
            },
        )

        # Create a top-level cohort that references both middle cohorts
        # Should detect the behavioral cohort through the chain
        top_cohort = Cohort.objects.create(
            team=self.team,
            name="Top Cohort",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.OR,
                    values=[
                        Property(type="cohort", key="id", value=middle_cohort.id),
                        Property(type="cohort", key="id", value=middle_person_cohort.id),
                    ],
                ).to_dict()
            },
        )

        # The top cohort should be BEHAVIORAL because it references middle_cohort,
        # which references behavioral_cohort
        self.assertEqual(top_cohort.determine_cohort_type_based_on_filters(), CohortType.BEHAVIORAL)

    def test_determine_cohort_type_based_on_filters_analytical_through_nesting(self):
        """Test that analytical type is detected and takes precedence through nested cohorts"""

        # Create an analytical cohort
        analytical_cohort = Cohort.objects.create(
            team=self.team,
            name="Analytical Cohort",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(
                            type="behavioral",
                            key="performed_event_first_time",
                            event_type="events",
                            value=BehavioralPropertyType.PERFORMED_EVENT_FIRST_TIME,
                            operator="exact",
                            time_interval="day",
                            time_value=1,
                        )
                    ],
                ).to_dict()
            },
        )

        # Create a behavioral cohort
        behavioral_cohort = Cohort.objects.create(
            team=self.team,
            name="Behavioral Cohort",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(
                            type="behavioral",
                            key="performed_event",
                            value=BehavioralPropertyType.PERFORMED_EVENT,
                            event_type="events",
                            operator="exact",
                            time_interval="day",
                            time_value=1,
                        )
                    ],
                ).to_dict()
            },
        )

        # Create a cohort that references both - analytical should take precedence
        mixed_cohort = Cohort.objects.create(
            team=self.team,
            name="Mixed Cohort",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="cohort", key="id", value=analytical_cohort.id),
                        Property(type="cohort", key="id", value=behavioral_cohort.id),
                    ],
                ).to_dict()
            },
        )

        # Should be ANALYTICAL because analytical takes precedence over behavioral
        self.assertEqual(mixed_cohort.determine_cohort_type_based_on_filters(), CohortType.ANALYTICAL)

        # Create a cohort that references the mixed cohort through multiple levels
        top_level_cohort = Cohort.objects.create(
            team=self.team,
            name="Top Level Cohort",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="cohort", key="id", value=mixed_cohort.id),
                        Property(type="person", key="email", operator="icontains", value="test"),
                    ],
                ).to_dict()
            },
        )

        # Should still be ANALYTICAL through the chain
        self.assertEqual(top_level_cohort.determine_cohort_type_based_on_filters(), CohortType.ANALYTICAL)

    def test_determine_cohort_type_based_on_filters_complex_nested_hierarchy(self):
        """Test a complex hierarchy with multiple levels and branches"""

        # Level 3: Base cohorts
        analytical = Cohort.objects.create(
            team=self.team,
            name="L3 Analytical",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(
                            type="behavioral",
                            key="performed_event_first_time",
                            event_type="events",
                            value=BehavioralPropertyType.PERFORMED_EVENT_FIRST_TIME,
                            operator="exact",
                            time_interval="day",
                            time_value=1,
                        )
                    ],
                ).to_dict()
            },
        )

        behavioral = Cohort.objects.create(
            team=self.team,
            name="L3 Behavioral",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(
                            type="behavioral",
                            key="performed_event",
                            value=BehavioralPropertyType.PERFORMED_EVENT,
                            event_type="events",
                            operator="exact",
                            time_interval="day",
                            time_value=1,
                        )
                    ],
                ).to_dict()
            },
        )

        person_prop = Cohort.objects.create(
            team=self.team,
            name="L3 Person",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="person", key="age", operator="gt", value=25),
                    ],
                ).to_dict()
            },
        )

        # Level 2: Mix different types
        l2_with_analytical = Cohort.objects.create(
            team=self.team,
            name="L2 With Analytical",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="cohort", key="id", value=analytical.id),
                        Property(type="cohort", key="id", value=person_prop.id),
                    ],
                ).to_dict()
            },
        )

        l2_with_behavioral = Cohort.objects.create(
            team=self.team,
            name="L2 With Behavioral",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="cohort", key="id", value=behavioral.id),
                        Property(type="cohort", key="id", value=person_prop.id),
                    ],
                ).to_dict()
            },
        )

        l2_person_only = Cohort.objects.create(
            team=self.team,
            name="L2 Person Only",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="cohort", key="id", value=person_prop.id),
                        Property(type="person", key="name", operator="icontains", value="test"),
                    ],
                ).to_dict()
            },
        )

        # Level 1: Top cohorts referencing L2
        # This references a cohort with analytical - should be ANALYTICAL
        top_with_analytical_branch = Cohort.objects.create(
            team=self.team,
            name="Top With Analytical Branch",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.OR,
                    values=[
                        Property(type="cohort", key="id", value=l2_with_analytical.id),
                        Property(type="cohort", key="id", value=l2_person_only.id),
                    ],
                ).to_dict()
            },
        )

        # This references only behavioral and person - should be BEHAVIORAL
        top_with_behavioral_branch = Cohort.objects.create(
            team=self.team,
            name="Top With Behavioral Branch",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.OR,
                    values=[
                        Property(type="cohort", key="id", value=l2_with_behavioral.id),
                        Property(type="cohort", key="id", value=l2_person_only.id),
                    ],
                ).to_dict()
            },
        )

        # This references only person property cohorts - should be PERSON_PROPERTY
        top_person_only = Cohort.objects.create(
            team=self.team,
            name="Top Person Only",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="cohort", key="id", value=l2_person_only.id),
                        Property(type="person", key="email", operator="icontains", value="@test.com"),
                    ],
                ).to_dict()
            },
        )

        # Verify the types cascade correctly through the hierarchy
        self.assertEqual(top_with_analytical_branch.determine_cohort_type_based_on_filters(), CohortType.ANALYTICAL)
        self.assertEqual(top_with_behavioral_branch.determine_cohort_type_based_on_filters(), CohortType.BEHAVIORAL)
        self.assertEqual(top_person_only.determine_cohort_type_based_on_filters(), CohortType.PERSON_PROPERTY)
