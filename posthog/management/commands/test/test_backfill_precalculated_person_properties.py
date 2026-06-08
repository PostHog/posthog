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
        assert mock_workflow.called
        call_args = mock_workflow.call_args[1]
        filters = call_args["filters"]
        cohort_ids = call_args["cohort_ids"]

        # Should have 1 filter shared by 2 cohorts
        assert len(filters) == 1
        assert set(cohort_ids) == {cohort1.id, cohort2.id}

        # The shared condition should be present with both cohorts
        assert filters[0].condition_hash == shared_condition_hash
        assert filters[0].bytecode == shared_bytecode
        assert set(filters[0].cohort_ids) == {cohort1.id, cohort2.id}

        # Verify output shows deduplication
        output = self.command_output.getvalue()
        assert "= Duplicate condition:" in output
        assert shared_condition_hash in output

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
        filters = call_args["filters"]
        cohort_ids = call_args["cohort_ids"]

        # Should have 2 unique filters and 3 cohorts
        assert len(filters) == 2
        assert set(cohort_ids) == {cohort1.id, cohort2.id, cohort3.id}

        # Find the age and country filters
        age_filter = next(f for f in filters if f.condition_hash == age_condition_hash)
        country_filter = next(f for f in filters if f.condition_hash == country_condition_hash)

        # Verify the age condition is shared by cohorts 1 and 2
        assert age_filter.bytecode == age_bytecode
        assert set(age_filter.cohort_ids) == {cohort1.id, cohort2.id}

        # Verify the country condition is shared by cohorts 1 and 3
        assert country_filter.bytecode == country_bytecode
        assert set(country_filter.cohort_ids) == {cohort1.id, cohort3.id}

        # Verify output shows deduplication for both shared conditions
        output = self.command_output.getvalue()
        assert "= Duplicate condition:" in output
        assert "reduced 4 filters to 2 unique conditions" in output

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
        filters = call_args["filters"]
        cohort_ids = call_args["cohort_ids"]

        # Should have 2 unique filters (no deduplication)
        assert len(filters) == 2
        assert len(cohort_ids) == 2

        # Each condition should be used by exactly one cohort
        for filter_obj in filters:
            assert len(filter_obj.cohort_ids) == 1

        # Verify output shows all new conditions
        output = self.command_output.getvalue()
        assert "+ New condition:" in output
        assert "= Duplicate condition:" not in output
        assert "reduced 2 filters to 2 unique conditions" in output

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
        filters = call_args["filters"]
        cohort_ids = call_args["cohort_ids"]

        # Should only have 1 cohort and 1 filter (the good one)
        assert len(filters) == 1
        assert cohort_ids == [good_cohort.id]

        # Verify output shows skipping
        output = self.command_output.getvalue()
        assert f"Skipping cohort {bad_cohort.id}: no person property filters" in output

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
        filters = call_args["filters"]
        cohort_ids = call_args["cohort_ids"]

        # Should have 1 unique filter (intra-cohort deduplication)
        assert len(filters) == 1
        assert len(cohort_ids) == 1

        # The condition should be present with the correct cohort
        filter_obj = filters[0]
        assert filter_obj.condition_hash == shared_condition_hash
        assert set(filter_obj.cohort_ids) == {cohort_ids[0]}

        # Verify the set-based deduplication worked
        output = self.command_output.getvalue()
        assert "reduced 2 filters to 1 unique conditions" in output
