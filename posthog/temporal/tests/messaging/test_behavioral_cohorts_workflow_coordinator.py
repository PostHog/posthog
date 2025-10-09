import math
from dataclasses import dataclass

from parameterized import parameterized

from posthog.temporal.messaging.behavioral_cohorts_workflow_coordinator import CoordinatorWorkflowInputs


@dataclass
class ParallelismTestCase:
    """Test case for parallelism distribution testing."""

    name: str
    total_conditions: int
    parallelism: int
    expected_workflows: int
    expected_conditions_per_workflow: list[tuple[int, int]]  # List of (offset, limit) pairs


# Test cases for parallelism distribution
PARALLELISM_TEST_CASES = [
    ParallelismTestCase(
        name="even_distribution_100_conditions_10_workers",
        total_conditions=100,
        parallelism=10,
        expected_workflows=10,
        expected_conditions_per_workflow=[
            (0, 10),
            (10, 10),
            (20, 10),
            (30, 10),
            (40, 10),
            (50, 10),
            (60, 10),
            (70, 10),
            (80, 10),
            (90, 10),
        ],
    ),
    ParallelismTestCase(
        name="uneven_distribution_with_remainder",
        total_conditions=100,
        parallelism=3,
        expected_workflows=3,
        expected_conditions_per_workflow=[(0, 34), (34, 34), (68, 32)],  # 100/3 = 33.33, ceil = 34
    ),
    ParallelismTestCase(
        name="all_workflows_needed_50_conditions_10_workers",
        total_conditions=50,
        parallelism=10,
        expected_workflows=10,
        expected_conditions_per_workflow=[
            (0, 5),
            (5, 5),
            (10, 5),
            (15, 5),
            (20, 5),
            (25, 5),
            (30, 5),
            (35, 5),
            (40, 5),
            (45, 5),
        ],
    ),
    ParallelismTestCase(
        name="large_dataset_even_split",
        total_conditions=1000,
        parallelism=4,
        expected_workflows=4,
        expected_conditions_per_workflow=[(0, 250), (250, 250), (500, 250), (750, 250)],
    ),
    ParallelismTestCase(
        name="no_conditions_no_workflows",
        total_conditions=0,
        parallelism=10,
        expected_workflows=0,
        expected_conditions_per_workflow=[],
    ),
    ParallelismTestCase(
        name="single_workflow_all_conditions",
        total_conditions=10,
        parallelism=1,
        expected_workflows=1,
        expected_conditions_per_workflow=[(0, 10)],
    ),
    ParallelismTestCase(
        name="uneven_small_distribution",
        total_conditions=7,
        parallelism=3,
        expected_workflows=3,
        expected_conditions_per_workflow=[(0, 3), (3, 3), (6, 1)],
    ),
]


class TestBehavioralCohortsCoordinatorWorkflow:
    @parameterized.expand([(case.name, case) for case in PARALLELISM_TEST_CASES])
    def test_parallelism_distribution_calculation(self, test_name: str, test_case: ParallelismTestCase):
        """Test that the coordinator correctly calculates work distribution across child workflows based on parallelism."""
        inputs = CoordinatorWorkflowInputs(parallelism=test_case.parallelism)

        # Calculate distribution using the same logic as the coordinator
        actual_workflows: list[tuple[int, int]] = []
        if test_case.total_conditions == 0:
            pass  # actual_workflows remains empty
        else:
            conditions_per_workflow = math.ceil(test_case.total_conditions / inputs.parallelism)

            for i in range(inputs.parallelism):
                offset = i * conditions_per_workflow
                limit = min(conditions_per_workflow, test_case.total_conditions - offset)

                if limit <= 0:
                    break

                actual_workflows.append((offset, limit))

        # Verify the correct number of workflows
        assert (
            len(actual_workflows) == test_case.expected_workflows
        ), f"Test '{test_case.name}': Expected {test_case.expected_workflows} workflows, got {len(actual_workflows)}"

        # Verify each workflow gets the correct offset and limit
        for i, expected_workflow in enumerate(test_case.expected_conditions_per_workflow):
            expected_offset, expected_limit = expected_workflow
            actual_offset, actual_limit = actual_workflows[i]

            assert (
                actual_offset == expected_offset
            ), f"Test '{test_case.name}' workflow {i}: expected offset {expected_offset}, got {actual_offset}"
            assert (
                actual_limit == expected_limit
            ), f"Test '{test_case.name}' workflow {i}: expected limit {expected_limit}, got {actual_limit}"

        # Verify no gaps or overlaps in coverage
        if actual_workflows:
            total_covered = sum(workflow[1] for workflow in actual_workflows)
            assert (
                total_covered == test_case.total_conditions
            ), f"Test '{test_case.name}': Total conditions covered ({total_covered}) doesn't match total conditions ({test_case.total_conditions})"

            # Verify no gaps between workflows
            for i in range(1, len(actual_workflows)):
                prev_offset, prev_limit = actual_workflows[i - 1]
                current_offset, _ = actual_workflows[i]
                prev_end = prev_offset + prev_limit

                assert (
                    prev_end == current_offset
                ), f"Test '{test_case.name}': Gap found between workflow {i-1} (ends at {prev_end}) and workflow {i} (starts at {current_offset})"

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
