import pytest
from unittest.mock import Mock, patch

from posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow import (
    BackfillPrecalculatedPersonPropertiesCoordinatorInputs,
    BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow,
    PersonIdRangesPageResult,
)


class TestBackfillPrecalculatedPersonPropertiesCoordinatorInputs:
    def test_properties_to_log(self):
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key-456",
            cohort_ids=[1, 2, 3],
            batch_size=500,
        )

        expected = {
            "team_id": 123,
            "cohort_count": 3,
            "cohort_ids": [1, 2, 3],
            "filter_storage_key": "test-key-456",
            "batch_size": 500,
            "concurrent_workflows": 5,
        }

        assert inputs.properties_to_log == expected

    def test_default_batch_size(self):
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1],
        )

        assert inputs.batch_size == 1000


class TestBackfillPrecalculatedPersonPropertiesCoordinatorWorkflow:
    def test_parse_inputs_raises_not_implemented(self):
        with pytest.raises(NotImplementedError):
            BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow.parse_inputs(["arg1", "arg2"])

    @pytest.mark.asyncio
    async def test_processes_ranges_with_concurrent_workflows(self):
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1, 2],
            batch_size=100,
            concurrent_workflows=2,
        )

        mock_workflow_info = Mock()
        mock_workflow_info.workflow_id = "test-coordinator-123"

        page_result = PersonIdRangesPageResult(
            ranges=[("person1", "person100")],
            cursor=None,
        )

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()

        child_workflows_started = []

        async def mock_start_child_workflow(inputs_arg, logger, batch_num, start_id, end_id, handles):
            child_workflows_started.append(
                {
                    "batch_number": batch_num,
                    "start_person_id": start_id,
                    "end_person_id": end_id,
                }
            )

        with (
            patch("temporalio.workflow.info", return_value=mock_workflow_info),
            patch("temporalio.workflow.execute_activity", return_value=page_result),
            patch.object(workflow, "_start_child_workflow_for_range", side_effect=mock_start_child_workflow),
            patch("asyncio.wait", return_value=(set(), set())),
            patch("temporalio.workflow.logger") as mock_logger,
        ):
            await workflow.run(inputs)

            assert len(child_workflows_started) == 1
            assert child_workflows_started[0]["batch_number"] == 1
            assert child_workflows_started[0]["start_person_id"] == "person1"
            assert child_workflows_started[0]["end_person_id"] == "person100"

            log_calls = [str(call) for call in mock_logger.info.call_args_list]
            assert any("completed successfully" in call for call in log_calls)

    @pytest.mark.asyncio
    async def test_handles_no_person_ranges(self):
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1],
            batch_size=100,
            concurrent_workflows=2,
        )

        mock_workflow_info = Mock()
        mock_workflow_info.workflow_id = "test-coordinator-no-ranges"

        empty_page = PersonIdRangesPageResult(ranges=[], cursor=None)

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()

        with (
            patch("temporalio.workflow.info", return_value=mock_workflow_info),
            patch("temporalio.workflow.execute_activity", return_value=empty_page),
            patch("temporalio.workflow.logger") as mock_logger,
        ):
            await workflow.run(inputs)

            log_calls = [str(call) for call in mock_logger.info.call_args_list]
            assert any("No persons found for team" in call for call in log_calls)

    @pytest.mark.asyncio
    async def test_paginates_through_multiple_pages(self):
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1],
            batch_size=100,
            concurrent_workflows=2,
        )

        mock_workflow_info = Mock()
        mock_workflow_info.workflow_id = "test-coordinator-multi-page"

        page1 = PersonIdRangesPageResult(
            ranges=[("person1", "person100"), ("person101", "person200")],
            cursor="person200",
        )
        page2 = PersonIdRangesPageResult(
            ranges=[("person201", "person300")],
            cursor=None,
        )

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()

        child_workflows_started = []
        call_count = 0

        async def mock_start_child_workflow(inputs_arg, logger, batch_num, start_id, end_id, handles):
            child_workflows_started.append(
                {
                    "batch_number": batch_num,
                    "start_person_id": start_id,
                    "end_person_id": end_id,
                }
            )

        def mock_execute_activity(activity, activity_inputs, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return page1
            return page2

        with (
            patch("temporalio.workflow.info", return_value=mock_workflow_info),
            patch("temporalio.workflow.execute_activity", side_effect=mock_execute_activity),
            patch.object(workflow, "_start_child_workflow_for_range", side_effect=mock_start_child_workflow),
            patch("asyncio.wait", return_value=(set(), set())),
            patch("temporalio.workflow.logger") as mock_logger,
        ):
            await workflow.run(inputs)

            assert len(child_workflows_started) == 3
            assert child_workflows_started[0]["start_person_id"] == "person1"
            assert child_workflows_started[1]["start_person_id"] == "person101"
            assert child_workflows_started[2]["start_person_id"] == "person201"

            log_calls = [str(call) for call in mock_logger.info.call_args_list]
            assert any("completed successfully" in call for call in log_calls)
