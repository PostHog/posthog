from posthog.models import Cohort
from posthog.models.cohort.util import (
    get_dependent_cohorts_reverse,
    validate_cohort_dependency_types,
    get_minimum_required_type_for_dependency,
)
from posthog.test.base import BaseTest


class TestCohortDependencyValidation(BaseTest):
    def test_get_dependent_cohorts_reverse(self):
        """Test that reverse dependency lookup works correctly"""
        # Create a base cohort
        base_cohort = Cohort.objects.create(
            team=self.team,
            name="Base Cohort",
            cohort_type="person_property",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {"type": "AND", "values": [{"key": "email", "type": "person", "value": "@posthog.com"}]}
                    ],
                }
            },
        )

        # Create a dependent cohort
        dependent_cohort = Cohort.objects.create(
            team=self.team,
            name="Dependent Cohort",
            cohort_type="person_property",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "AND", "values": [{"key": "id", "type": "cohort", "value": base_cohort.id}]}],
                }
            },
        )

        # Test that we find the dependency
        dependents = get_dependent_cohorts_reverse(base_cohort)
        self.assertEqual(len(dependents), 1)
        self.assertEqual(dependents[0].id, dependent_cohort.id)

    def test_get_minimum_required_type_for_dependency(self):
        """Test type hierarchy calculations"""
        # Static -> PersonProperty should require PersonProperty
        self.assertEqual(get_minimum_required_type_for_dependency("person_property", "static"), "person_property")

        # Behavioral -> PersonProperty should require Behavioral
        self.assertEqual(get_minimum_required_type_for_dependency("behavioral", "person_property"), "behavioral")

        # PersonProperty -> Behavioral should stay Behavioral (already higher)
        self.assertEqual(get_minimum_required_type_for_dependency("person_property", "behavioral"), "behavioral")

        # Analytical -> Behavioral should require Analytical
        self.assertEqual(get_minimum_required_type_for_dependency("analytical", "behavioral"), "analytical")

    def test_validate_cohort_dependency_types(self):
        """Test dependency validation when changing cohort types"""
        # Create base cohort
        base_cohort = Cohort.objects.create(team=self.team, name="Base Cohort", cohort_type="person_property")

        # Create dependent cohort
        dependent_cohort = Cohort.objects.create(
            team=self.team,
            name="Dependent Cohort",
            cohort_type="person_property",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "AND", "values": [{"key": "id", "type": "cohort", "value": base_cohort.id}]}],
                }
            },
        )

        # Changing base to behavioral should require dependent to become behavioral
        affected = validate_cohort_dependency_types(base_cohort, "behavioral")
        self.assertEqual(len(affected), 1)
        self.assertEqual(affected[0][0].id, dependent_cohort.id)
        self.assertEqual(affected[0][1], "behavioral")

        # Changing base to analytical should require dependent to become analytical
        affected = validate_cohort_dependency_types(base_cohort, "analytical")
        self.assertEqual(len(affected), 1)
        self.assertEqual(affected[0][0].id, dependent_cohort.id)
        self.assertEqual(affected[0][1], "analytical")

        # Changing to static should not affect dependents (static doesn't propagate upward)
        affected = validate_cohort_dependency_types(base_cohort, "static")
        self.assertEqual(len(affected), 0)
