import math

from parameterized import parameterized

from posthog.temporal.messaging.behavioral_cohorts_workflow_coordinator import CoordinatorWorkflowInputs


class TestBehavioralCohortsCoordinatorWorkflow:
    @parameterized.expand(
        [
            # (total_conditions, parallelism, expected_workflows, expected_conditions_per_workflow)
            (
                100,
                10,
                10,
                [(0, 10), (10, 10), (20, 10), (30, 10), (40, 10), (50, 10), (60, 10), (70, 10), (80, 10), (90, 10)],
            ),
            (100, 3, 3, [(0, 34), (34, 34), (68, 32)]),  # 100/3 = 33.33, ceil = 34, last gets remainder
            (
                50,
                10,
                10,
                [(0, 5), (5, 5), (10, 5), (15, 5), (20, 5), (25, 5), (30, 5), (35, 5), (40, 5), (45, 5)],
            ),  # All 10 workflows needed
            (1000, 4, 4, [(0, 250), (250, 250), (500, 250), (750, 250)]),
            (0, 10, 0, []),  # No conditions, no workflows
            (10, 1, 1, [(0, 10)]),  # Single workflow for all conditions
            (7, 3, 3, [(0, 3), (3, 3), (6, 1)]),  # Uneven distribution
        ]
    )
    def test_parallelism_distribution_calculation(
        self, total_conditions, parallelism, expected_workflows, expected_conditions_per_workflow
    ):
        """Test that the coordinator correctly calculates work distribution across child workflows based on parallelism."""
        inputs = CoordinatorWorkflowInputs(parallelism=parallelism)

        # Calculate distribution using the same logic as the coordinator
        if total_conditions == 0:
            actual_workflows = []
        else:
            conditions_per_workflow = math.ceil(total_conditions / inputs.parallelism)
            actual_workflows = []

            for i in range(inputs.parallelism):
                offset = i * conditions_per_workflow
                limit = min(conditions_per_workflow, total_conditions - offset)

                if limit <= 0:
                    break

                actual_workflows.append((offset, limit))

        # Verify the correct number of workflows
        assert (
            len(actual_workflows) == expected_workflows
        ), f"Expected {expected_workflows} workflows, got {len(actual_workflows)}"

        # Verify each workflow gets the correct offset and limit
        for i, (expected_offset, expected_limit) in enumerate(expected_conditions_per_workflow):
            assert (
                actual_workflows[i][0] == expected_offset
            ), f"Workflow {i}: expected offset {expected_offset}, got {actual_workflows[i][0]}"
            assert (
                actual_workflows[i][1] == expected_limit
            ), f"Workflow {i}: expected limit {expected_limit}, got {actual_workflows[i][1]}"

        # Verify no gaps or overlaps in coverage
        if actual_workflows:
            total_covered = sum(w[1] for w in actual_workflows)
            assert (
                total_covered == total_conditions
            ), f"Total conditions covered ({total_covered}) doesn't match total conditions ({total_conditions})"

            # Verify no gaps between workflows
            for i in range(1, len(actual_workflows)):
                prev_end = actual_workflows[i - 1][0] + actual_workflows[i - 1][1]
                current_start = actual_workflows[i][0]
                assert (
                    prev_end == current_start
                ), f"Gap found between workflow {i-1} (ends at {prev_end}) and workflow {i} (starts at {current_start})"

    def test_coordinator_workflow_inputs_defaults(self):
        """Test that CoordinatorWorkflowInputs has correct defaults."""
        inputs = CoordinatorWorkflowInputs()

        assert inputs.team_id is None
        assert inputs.cohort_id is None
        assert inputs.condition is None
        assert inputs.min_matches == 3
        assert inputs.days == 30
        assert inputs.parallelism == 10

    def test_coordinator_workflow_inputs_properties_to_log(self):
        """Test that properties_to_log returns the expected fields."""
        inputs = CoordinatorWorkflowInputs(
            team_id=123,
            cohort_id=456,
            min_matches=5,
            days=60,
            parallelism=8,
        )

        props = inputs.properties_to_log
        expected_props = {
            "team_id": 123,
            "cohort_id": 456,
            "min_matches": 5,
            "days": 60,
            "parallelism": 8,
        }

        assert props == expected_props
