from posthog.models import Cohort
from posthog.models.cohort.cohort import CohortType
from posthog.models.cohort.validation import validate_cohort_type_against_data, determine_cohort_type_from_data
from posthog.models.property import Property, PropertyGroup, PropertyOperatorType, BehavioralPropertyType
from posthog.test.base import BaseTest


class TestCohortValidation(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False  # So that each test gets a different team_id, ensuring separation of CH data

    def test_determine_cohort_type_from_data_static(self):
        """Static cohorts should always return STATIC type"""
        data = {"is_static": True}
        result = determine_cohort_type_from_data(data, self.team.id)
        self.assertEqual(result, CohortType.STATIC)

    def test_determine_cohort_type_from_data_query_based(self):
        """Query-based cohorts should always return ANALYTICAL type"""
        data = {"query": {"kind": "EventsQuery"}}
        result = determine_cohort_type_from_data(data, self.team.id)
        self.assertEqual(result, CohortType.ANALYTICAL)

    def test_determine_cohort_type_from_data_person_property(self):
        """Cohorts with only person property filters should return PERSON_PROPERTY"""
        data = {
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "person", "key": "email", "operator": "icontains", "value": "@posthog.com"},
                        {"type": "person", "key": "age", "operator": "gt", "value": "18"},
                    ],
                }
            }
        }
        result = determine_cohort_type_from_data(data, self.team.id)
        self.assertEqual(result, CohortType.PERSON_PROPERTY)

    def test_determine_cohort_type_from_data_behavioral(self):
        """Cohorts with behavioral filters should return BEHAVIORAL"""
        data = {
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "performed_event",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 1,
                        }
                    ],
                }
            }
        }
        result = determine_cohort_type_from_data(data, self.team.id)
        self.assertEqual(result, CohortType.BEHAVIORAL)

    def test_determine_cohort_type_from_data_analytical(self):
        """Cohorts with analytical filters should return ANALYTICAL"""
        data = {
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "performed_event_first_time",
                            "value": "performed_event_first_time",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 1,
                        }
                    ],
                }
            }
        }
        result = determine_cohort_type_from_data(data, self.team.id)
        self.assertEqual(result, CohortType.ANALYTICAL)

    def test_determine_cohort_type_from_data_hierarchy(self):
        """Mixed filters should return the highest complexity type"""
        data = {
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "person", "key": "email", "operator": "icontains", "value": "@posthog.com"},
                        {
                            "type": "behavioral",
                            "key": "performed_event",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 1,
                        },
                        {
                            "type": "behavioral",
                            "key": "performed_event_first_time",
                            "value": "performed_event_first_time",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 1,
                        },
                    ],
                }
            }
        }
        result = determine_cohort_type_from_data(data, self.team.id)
        # Should return ANALYTICAL since it has the highest complexity
        self.assertEqual(result, CohortType.ANALYTICAL)

    def test_determine_cohort_type_from_data_with_cohort_reference(self):
        """Cohort referencing another should inherit the higher complexity type"""
        # Create a behavioral cohort first
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

        # Test data that references this cohort
        data = {
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "person", "key": "email", "operator": "icontains", "value": "@posthog.com"},
                        {"type": "cohort", "key": "id", "value": behavioral_cohort.id},
                    ],
                }
            }
        }
        result = determine_cohort_type_from_data(data, self.team.id)
        # Should return BEHAVIORAL because it references a behavioral cohort
        self.assertEqual(result, CohortType.BEHAVIORAL)

    def test_determine_cohort_type_from_data_circular_reference_error(self):
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

        # Test data that would create circular reference
        data = {
            "filters": {
                "properties": {"type": "AND", "values": [{"type": "cohort", "key": "id", "value": cohort_a.id}]}
            }
        }

        # Should raise an error for circular references
        with self.assertRaises(ValueError) as cm:
            determine_cohort_type_from_data(data, self.team.id)
        self.assertIn("Circular cohort reference detected", str(cm.exception))

    def test_determine_cohort_type_from_data_missing_cohort_error(self):
        """Should raise error when referencing non-existent cohorts"""
        data = {
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "cohort",
                            "key": "id",
                            "value": 99999,  # Non-existent ID
                        },
                        {"type": "person", "key": "name", "operator": "icontains", "value": "test"},
                    ],
                }
            }
        }

        # Should raise an error for missing cohort references
        with self.assertRaises(ValueError) as cm:
            determine_cohort_type_from_data(data, self.team.id)
        self.assertIn("not found", str(cm.exception))

    def test_determine_cohort_type_from_data_empty_cohort_error(self):
        """Should raise error for cohorts with no filters"""
        data = {"filters": {"properties": {"type": "AND", "values": []}}}

        with self.assertRaises(ValueError) as cm:
            determine_cohort_type_from_data(data, self.team.id)
        self.assertIn("no valid filters found", str(cm.exception))

    def test_validate_cohort_type_against_data_valid_match(self):
        """Should pass validation when cohort type matches filters"""
        data = {
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [{"type": "person", "key": "email", "operator": "icontains", "value": "@posthog.com"}],
                }
            }
        }

        is_valid, error_msg = validate_cohort_type_against_data("person_property", data, self.team.id)
        self.assertTrue(is_valid)
        self.assertIsNone(error_msg)

    def test_validate_cohort_type_against_data_mismatch(self):
        """Should fail validation when provided type doesn't exactly match required type"""
        data = {
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "performed_event",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 1,
                        }
                    ],
                }
            }
        }

        # Test with lower complexity type
        is_valid, error_msg = validate_cohort_type_against_data("person_property", data, self.team.id)
        self.assertFalse(is_valid)
        self.assertIsNotNone(error_msg)
        assert error_msg is not None  # Type narrowing for mypy
        self.assertIn("does not match the filters", error_msg)
        self.assertIn("Expected type: 'behavioral'", error_msg)

        # Test with higher complexity type (also fails now)
        is_valid, error_msg = validate_cohort_type_against_data("analytical", data, self.team.id)
        self.assertFalse(is_valid)
        self.assertIsNotNone(error_msg)
        assert error_msg is not None  # Type narrowing for mypy
        self.assertIn("does not match the filters", error_msg)
        self.assertIn("Expected type: 'behavioral'", error_msg)

    def test_validate_cohort_type_against_data_invalid_type(self):
        """Should fail validation for invalid cohort type strings"""
        data = {"is_static": True}

        is_valid, error_msg = validate_cohort_type_against_data("invalid_type", data, self.team.id)
        self.assertFalse(is_valid)
        self.assertIsNotNone(error_msg)
        assert error_msg is not None  # Type narrowing for mypy
        self.assertIn('"invalid_type" is not a valid choice.', error_msg)

    def test_determine_cohort_type_from_data_nested_behavioral(self):
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

        # Test data referencing the behavioral cohort - should be BEHAVIORAL
        behavioral_ref_data = {
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "cohort", "key": "id", "value": behavioral_cohort.id},
                        {"type": "person", "key": "name", "operator": "icontains", "value": "test"},
                    ],
                }
            }
        }
        result = determine_cohort_type_from_data(behavioral_ref_data, self.team.id)
        self.assertEqual(result, CohortType.BEHAVIORAL)

        # Test data referencing only the person property cohort - should be PERSON_PROPERTY
        person_ref_data = {
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "cohort", "key": "id", "value": person_cohort.id},
                        {"type": "person", "key": "age", "operator": "gt", "value": 18},
                    ],
                }
            }
        }
        result = determine_cohort_type_from_data(person_ref_data, self.team.id)
        self.assertEqual(result, CohortType.PERSON_PROPERTY)

    def test_determine_cohort_type_from_data_deeply_nested_behavioral(self):
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

        # Test data that references both middle cohorts
        # Should detect the behavioral cohort through the chain
        data = {
            "filters": {
                "properties": {
                    "type": "OR",
                    "values": [
                        {"type": "cohort", "key": "id", "value": middle_cohort.id},
                        {"type": "cohort", "key": "id", "value": middle_person_cohort.id},
                    ],
                }
            }
        }

        result = determine_cohort_type_from_data(data, self.team.id)
        # Should be BEHAVIORAL because it references middle_cohort, which references behavioral_cohort
        self.assertEqual(result, CohortType.BEHAVIORAL)

    def test_determine_cohort_type_from_data_analytical_through_nesting(self):
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

        # Test data that references both - analytical should take precedence
        mixed_data = {
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "cohort", "key": "id", "value": analytical_cohort.id},
                        {"type": "cohort", "key": "id", "value": behavioral_cohort.id},
                    ],
                }
            }
        }

        result = determine_cohort_type_from_data(mixed_data, self.team.id)
        # Should be ANALYTICAL because analytical takes precedence over behavioral
        self.assertEqual(result, CohortType.ANALYTICAL)

    def test_determine_cohort_type_from_data_complex_nested_hierarchy(self):
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

        # Level 1: Test data referencing L2 cohorts
        # This references a cohort with analytical - should be ANALYTICAL
        top_with_analytical_data = {
            "filters": {
                "properties": {
                    "type": "OR",
                    "values": [
                        {"type": "cohort", "key": "id", "value": l2_with_analytical.id},
                        {"type": "cohort", "key": "id", "value": l2_person_only.id},
                    ],
                }
            }
        }

        # This references only behavioral and person - should be BEHAVIORAL
        top_with_behavioral_data = {
            "filters": {
                "properties": {
                    "type": "OR",
                    "values": [
                        {"type": "cohort", "key": "id", "value": l2_with_behavioral.id},
                        {"type": "cohort", "key": "id", "value": l2_person_only.id},
                    ],
                }
            }
        }

        # This references only person property cohorts - should be PERSON_PROPERTY
        top_person_only_data = {
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "cohort", "key": "id", "value": l2_person_only.id},
                        {"type": "person", "key": "email", "operator": "icontains", "value": "@test.com"},
                    ],
                }
            }
        }

        # Verify the types cascade correctly through the hierarchy
        self.assertEqual(determine_cohort_type_from_data(top_with_analytical_data, self.team.id), CohortType.ANALYTICAL)
        self.assertEqual(determine_cohort_type_from_data(top_with_behavioral_data, self.team.id), CohortType.BEHAVIORAL)
        self.assertEqual(
            determine_cohort_type_from_data(top_person_only_data, self.team.id), CohortType.PERSON_PROPERTY
        )
