from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from posthog.models import Cohort
from posthog.models.cohort.cohort import CohortType


class BackfillPrecalculatedPersonPropertiesCommandTestCase(BaseTest):
    """Tests for the backfill_precalculated_person_properties management command."""

    def setUp(self):
        super().setUp()
        self.command_output = StringIO()

    def test_cross_cohort_deduplication_single_shared_condition(self):
        """Test that filters with the same condition_hash are deduplicated across cohorts."""

        # Create cohorts with shared condition_hash
        shared_condition_hash = "age_filter_25_exact"
        shared_bytecode = ["mock_bytecode_age_25"]

        cohort1 = Cohort.objects.create(
            team=self.team,
            name="Young Users A",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "person",
                            "key": "age",
                            "value": 25,
                            "operator": "exact",
                            "conditionHash": shared_condition_hash,
                            "bytecode": shared_bytecode,
                        }
                    ],
                }
            },
        )

        cohort2 = Cohort.objects.create(
            team=self.team,
            name="Young Users B",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "person",
                            "key": "age",
                            "value": 25,
                            "operator": "exact",
                            "conditionHash": shared_condition_hash,
                            "bytecode": shared_bytecode,
                        }
                    ],
                }
            },
        )

        # Mock the workflow run to capture the inputs
        with patch(
            "posthog.management.commands.backfill_precalculated_person_properties.Command.run_temporal_workflow"
        ) as mock_workflow:
            mock_workflow.return_value = "test-workflow-id"

            call_command(
                "backfill_precalculated_person_properties", "--team-id", str(self.team.id), stdout=self.command_output
            )

        # Verify the workflow was called
        self.assertTrue(mock_workflow.called)
        call_args = mock_workflow.call_args[1]
        cohort_filters = call_args["cohort_filters"]

        # Should have 2 cohort filters (one per cohort)
        self.assertEqual(len(cohort_filters), 2)

        # Both cohorts should have the same filter (since they share the condition_hash)
        cohort1_filters = next(cf.filters for cf in cohort_filters if cf.cohort_id == cohort1.id)
        cohort2_filters = next(cf.filters for cf in cohort_filters if cf.cohort_id == cohort2.id)

        self.assertEqual(len(cohort1_filters), 1)
        self.assertEqual(len(cohort2_filters), 1)

        # Both filters should have the same condition_hash and bytecode
        self.assertEqual(cohort1_filters[0].condition_hash, shared_condition_hash)
        self.assertEqual(cohort2_filters[0].condition_hash, shared_condition_hash)
        self.assertEqual(cohort1_filters[0].bytecode, shared_bytecode)
        self.assertEqual(cohort2_filters[0].bytecode, shared_bytecode)

        # Verify output shows deduplication
        output = self.command_output.getvalue()
        self.assertIn("= Duplicate condition:", output)
        self.assertIn(shared_condition_hash, output)

    def test_cross_cohort_deduplication_multiple_shared_conditions(self):
        """Test deduplication with multiple shared conditions across three cohorts."""

        age_condition_hash = "age_filter_25"
        age_bytecode = ["mock_bytecode_age_25"]
        country_condition_hash = "country_filter_us"
        country_bytecode = ["mock_bytecode_country_us"]

        # Cohort 1: Age + Country filters
        cohort1 = Cohort.objects.create(
            team=self.team,
            name="Young US Users",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "person",
                            "key": "age",
                            "value": 25,
                            "operator": "exact",
                            "conditionHash": age_condition_hash,
                            "bytecode": age_bytecode,
                        },
                        {
                            "type": "person",
                            "key": "country",
                            "value": "US",
                            "operator": "exact",
                            "conditionHash": country_condition_hash,
                            "bytecode": country_bytecode,
                        },
                    ],
                }
            },
        )

        # Cohort 2: Only Age filter (shared)
        cohort2 = Cohort.objects.create(
            team=self.team,
            name="Young Users",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "person",
                            "key": "age",
                            "value": 25,
                            "operator": "exact",
                            "conditionHash": age_condition_hash,
                            "bytecode": age_bytecode,
                        }
                    ],
                }
            },
        )

        # Cohort 3: Only Country filter (shared)
        cohort3 = Cohort.objects.create(
            team=self.team,
            name="US Users",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "person",
                            "key": "country",
                            "value": "US",
                            "operator": "exact",
                            "conditionHash": country_condition_hash,
                            "bytecode": country_bytecode,
                        }
                    ],
                }
            },
        )

        with patch(
            "posthog.management.commands.backfill_precalculated_person_properties.Command.run_temporal_workflow"
        ) as mock_workflow:
            mock_workflow.return_value = "test-workflow-id"

            call_command(
                "backfill_precalculated_person_properties", "--team-id", str(self.team.id), stdout=self.command_output
            )

        call_args = mock_workflow.call_args[1]
        cohort_filters = call_args["cohort_filters"]

        # Should have 3 cohort filters
        self.assertEqual(len(cohort_filters), 3)

        # Verify each cohort gets only its own filters
        cohort1_filters = next(cf.filters for cf in cohort_filters if cf.cohort_id == cohort1.id)
        cohort2_filters = next(cf.filters for cf in cohort_filters if cf.cohort_id == cohort2.id)
        cohort3_filters = next(cf.filters for cf in cohort_filters if cf.cohort_id == cohort3.id)

        # Cohort 1 should have both age and country filters
        self.assertEqual(len(cohort1_filters), 2)
        cohort1_condition_hashes = {f.condition_hash for f in cohort1_filters}
        self.assertEqual(cohort1_condition_hashes, {age_condition_hash, country_condition_hash})

        # Cohort 2 should have only age filter
        self.assertEqual(len(cohort2_filters), 1)
        self.assertEqual(cohort2_filters[0].condition_hash, age_condition_hash)

        # Cohort 3 should have only country filter
        self.assertEqual(len(cohort3_filters), 1)
        self.assertEqual(cohort3_filters[0].condition_hash, country_condition_hash)

        # Verify output shows deduplication for both shared conditions
        output = self.command_output.getvalue()
        self.assertIn("= Duplicate condition:", output)
        self.assertIn("reduced 4 filters to 2 unique conditions", output)

    def test_no_deduplication_when_all_conditions_unique(self):
        """Test that no deduplication occurs when all conditions are unique."""

        Cohort.objects.create(
            team=self.team,
            name="Young Users",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "person",
                            "key": "age",
                            "value": 25,
                            "operator": "exact",
                            "conditionHash": "age_filter_25",
                            "bytecode": ["mock_bytecode_age_25"],
                        }
                    ],
                }
            },
        )

        Cohort.objects.create(
            team=self.team,
            name="Old Users",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "person",
                            "key": "age",
                            "value": 65,
                            "operator": "exact",
                            "conditionHash": "age_filter_65",
                            "bytecode": ["mock_bytecode_age_65"],
                        }
                    ],
                }
            },
        )

        with patch(
            "posthog.management.commands.backfill_precalculated_person_properties.Command.run_temporal_workflow"
        ) as mock_workflow:
            mock_workflow.return_value = "test-workflow-id"

            call_command(
                "backfill_precalculated_person_properties", "--team-id", str(self.team.id), stdout=self.command_output
            )

        call_args = mock_workflow.call_args[1]
        cohort_filters = call_args["cohort_filters"]

        # Should have 2 cohort filters
        self.assertEqual(len(cohort_filters), 2)

        # Each cohort should have exactly one unique filter
        for cf in cohort_filters:
            self.assertEqual(len(cf.filters), 1)

        # Verify output shows all new conditions
        output = self.command_output.getvalue()
        self.assertIn("+ New condition:", output)
        self.assertNotIn("= Duplicate condition:", output)
        self.assertIn("reduced 2 filters to 2 unique conditions", output)

    def test_skips_cohorts_without_person_property_filters(self):
        """Test that cohorts without person property filters are skipped."""

        # Create one cohort with person property filters
        good_cohort = Cohort.objects.create(
            team=self.team,
            name="Good Cohort",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "person",
                            "key": "age",
                            "value": 25,
                            "operator": "exact",
                            "conditionHash": "age_filter_25",
                            "bytecode": ["mock_bytecode_age_25"],
                        }
                    ],
                }
            },
        )

        # Create cohort without person property filters
        bad_cohort = Cohort.objects.create(
            team=self.team,
            name="Bad Cohort",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "event",  # Not a person property filter
                            "key": "event_name",
                            "value": "signup",
                            "operator": "exact",
                        }
                    ],
                }
            },
        )

        with patch(
            "posthog.management.commands.backfill_precalculated_person_properties.Command.run_temporal_workflow"
        ) as mock_workflow:
            mock_workflow.return_value = "test-workflow-id"

            call_command(
                "backfill_precalculated_person_properties", "--team-id", str(self.team.id), stdout=self.command_output
            )

        call_args = mock_workflow.call_args[1]
        cohort_filters = call_args["cohort_filters"]

        # Should only have 1 cohort filter (the good one)
        self.assertEqual(len(cohort_filters), 1)
        self.assertEqual(cohort_filters[0].cohort_id, good_cohort.id)

        # Verify output shows skipping
        output = self.command_output.getvalue()
        self.assertIn(f"Skipping cohort {bad_cohort.id}: no person property filters", output)

    def test_preserves_duplicate_condition_within_same_cohort(self):
        """Test that duplicate condition_hash within same cohort doesn't create duplicate entries."""

        shared_condition_hash = "age_filter_25"
        shared_bytecode = ["mock_bytecode_age_25"]

        # Create cohort with duplicate condition_hash within same cohort
        Cohort.objects.create(
            team=self.team,
            name="Cohort with Duplicates",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "person",
                            "key": "age",
                            "value": 25,
                            "operator": "exact",
                            "conditionHash": shared_condition_hash,
                            "bytecode": shared_bytecode,
                        },
                        {
                            "type": "person",
                            "key": "age",  # Same condition appears twice
                            "value": 25,
                            "operator": "exact",
                            "conditionHash": shared_condition_hash,  # Same hash
                            "bytecode": shared_bytecode,
                        },
                    ],
                }
            },
        )

        with patch(
            "posthog.management.commands.backfill_precalculated_person_properties.Command.run_temporal_workflow"
        ) as mock_workflow:
            mock_workflow.return_value = "test-workflow-id"

            call_command(
                "backfill_precalculated_person_properties", "--team-id", str(self.team.id), stdout=self.command_output
            )

        call_args = mock_workflow.call_args[1]
        cohort_filters = call_args["cohort_filters"]

        # Should have 1 cohort filter
        self.assertEqual(len(cohort_filters), 1)

        # The cohort should only get one copy of the filter (deduplicated)
        self.assertEqual(len(cohort_filters[0].filters), 1)
        self.assertEqual(cohort_filters[0].filters[0].condition_hash, shared_condition_hash)

        # Verify the set-based deduplication worked
        output = self.command_output.getvalue()
        self.assertIn("reduced 2 filters to 1 unique conditions", output)
