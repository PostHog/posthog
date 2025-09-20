from posthog.test.base import BaseTest

from posthog.models import Cohort
from posthog.models.cohort.validation import CohortTypeValidationSerializer
from posthog.models.property import BehavioralPropertyType, Property, PropertyGroup, PropertyOperatorType


class TestCohortTypeValidationSerializer(BaseTest):
    """Test the CohortTypeValidationSerializer directly"""

    CLASS_DATA_LEVEL_SETUP = False  # So that each test gets a different team_id, ensuring separation of CH data

    def test_validates_matching_cohort_type(self):
        """Should validate when provided type matches filters"""
        data = {
            "cohort_type": "person_property",
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [{"type": "person", "key": "email", "operator": "icontains", "value": "@posthog.com"}],
                }
            },
        }

        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertTrue(serializer.is_valid())

    def test_rejects_mismatched_cohort_type(self):
        """Should reject when provided type doesn't match filters"""
        data = {
            "cohort_type": "person_property",  # Wrong - should be behavioral
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
            },
        }

        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertFalse(serializer.is_valid())
        self.assertIn("cohort_type", serializer.errors)
        self.assertIn("does not match the filters", str(serializer.errors["cohort_type"]))
        self.assertIn("Expected type: 'behavioral'", str(serializer.errors["cohort_type"]))

    def test_static_cohort_type(self):
        """Static cohorts should validate as STATIC type"""
        data = {
            "cohort_type": "static",
            "is_static": True,
        }

        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertTrue(serializer.is_valid())

        # Wrong type for static
        data["cohort_type"] = "behavioral"
        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertFalse(serializer.is_valid())

    def test_query_based_cohort_type(self):
        """Query-based cohorts should validate as ANALYTICAL type"""
        data = {
            "cohort_type": "analytical",
            "query": {"kind": "EventsQuery"},
        }

        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertTrue(serializer.is_valid())

        # Wrong type for query-based
        data["cohort_type"] = "behavioral"
        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertFalse(serializer.is_valid())

    def test_analytical_behavioral_filters(self):
        """Analytical behavioral filters should validate as ANALYTICAL"""
        data = {
            "cohort_type": "analytical",
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "performed_event_first_time",
                            "value": "performed_event_first_time",
                            "event_type": "events",
                        }
                    ],
                }
            },
        }

        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertTrue(serializer.is_valid())

    def test_mixed_filters_highest_complexity(self):
        """Mixed filters should require the highest complexity type"""
        data = {
            "cohort_type": "analytical",  # Highest complexity in the mix
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
                        },
                        {
                            "type": "behavioral",
                            "key": "performed_event_first_time",
                            "value": "performed_event_first_time",
                            "event_type": "events",
                        },
                    ],
                }
            },
        }

        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertTrue(serializer.is_valid())

        # Should reject lower complexity types
        data["cohort_type"] = "behavioral"
        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertFalse(serializer.is_valid())

        data["cohort_type"] = "person_property"
        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertFalse(serializer.is_valid())

    def test_cohort_reference_inherits_type(self):
        """Cohort references should inherit the referenced cohort's type"""
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

        data = {
            "cohort_type": "behavioral",  # Should inherit behavioral from reference
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "cohort", "key": "id", "value": behavioral_cohort.id},
                        {"type": "person", "key": "name", "operator": "icontains", "value": "test"},
                    ],
                }
            },
        }

        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertTrue(serializer.is_valid())

        # Should reject if we claim it's just person_property
        data["cohort_type"] = "person_property"
        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertFalse(serializer.is_valid())

    def test_circular_reference_detection(self):
        """Should detect circular cohort references"""
        # Create two cohorts that reference each other
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
                values=[Property(type="cohort", key="id", value=cohort_a.id)],
            ).to_dict()
        }
        cohort_b.save()

        data = {
            "filters": {
                "properties": {"type": "AND", "values": [{"type": "cohort", "key": "id", "value": cohort_a.id}]}
            }
        }

        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertFalse(serializer.is_valid())
        # The error will be in non_field_errors since it happens during general validation
        self.assertTrue(any("Circular cohort reference" in str(e) for e in serializer.errors.values()))

    def test_missing_cohort_reference(self):
        """Should error when referencing non-existent cohorts"""
        data = {
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "cohort", "key": "id", "value": 99999},  # Non-existent
                    ],
                }
            }
        }

        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertFalse(serializer.is_valid())
        self.assertTrue(any("not found" in str(e) for e in serializer.errors.values()))

    def test_empty_filters_error(self):
        """Should error for cohorts with no valid filters"""
        data = {"filters": {"properties": {"type": "AND", "values": []}}}

        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertFalse(serializer.is_valid())
        self.assertTrue(any("no valid filters" in str(e) for e in serializer.errors.values()))

    def test_no_cohort_type_provided_passes_validation(self):
        """When no cohort_type is provided, validation should pass"""
        data = {
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [{"type": "person", "key": "email", "operator": "icontains", "value": "@posthog.com"}],
                }
            }
        }

        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertTrue(serializer.is_valid())
        # No cohort_type in validated_data since it wasn't provided
        self.assertNotIn("cohort_type", serializer.validated_data)

    def test_nested_property_groups(self):
        """Should handle nested property groups correctly"""
        data = {
            "cohort_type": "behavioral",
            "filters": {
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"type": "person", "key": "email", "operator": "icontains", "value": "@example.com"}
                            ],
                        },
                        {"type": "behavioral", "key": "pageview", "value": "performed_event", "event_type": "events"},
                    ],
                }
            },
        }

        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertTrue(serializer.is_valid())

        # Should reject if claiming it's person_property when it has behavioral
        data["cohort_type"] = "person_property"
        serializer = CohortTypeValidationSerializer(data=data, team_id=self.team.id)
        self.assertFalse(serializer.is_valid())
