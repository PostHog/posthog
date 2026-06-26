from types import TracebackType

import pytest
from unittest.mock import Mock, patch

import temporalio.exceptions

from posthog.hogql import ast

from posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow import (
    BackfillPrecalculatedPersonPropertiesCoordinatorInputs,
    BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow,
    PersonIdRangesPageInputs,
    PersonIdRangesPageResult,
    get_person_id_ranges_page_activity,
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
    async def test_raises_when_child_workflow_fails(self):
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1],
            batch_size=100,
            concurrent_workflows=2,
        )

        mock_workflow_info = Mock()
        mock_workflow_info.workflow_id = "test-coordinator-failure"

        page_result = PersonIdRangesPageResult(ranges=[("person1", "person100")], cursor=None)

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()

        class _FailingHandle:
            def __await__(self):
                async def _coro():
                    raise RuntimeError("child boom")

                return _coro().__await__()

        failing_handle = _FailingHandle()

        async def mock_start_child_workflow(inputs_arg, logger, batch_num, start_id, end_id, handles):
            handles.append(failing_handle)

        with (
            patch("temporalio.workflow.info", return_value=mock_workflow_info),
            patch("temporalio.workflow.execute_activity", return_value=page_result),
            patch.object(workflow, "_start_child_workflow_for_range", side_effect=mock_start_child_workflow),
            patch("asyncio.wait", return_value=({failing_handle}, set())),
            patch("temporalio.workflow.logger"),
        ):
            with pytest.raises(temporalio.exceptions.ApplicationError, match="child workflows failed"):
                await workflow.run(inputs)

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


def aiter(iterable):
    """Wrap a plain iterable as an async iterator for use in tests."""

    async def _aiter():
        for item in iterable:
            yield item

    return _aiter()


class _AsyncClientContextManager:
    def __init__(self, client: Mock) -> None:
        self.client = client

    async def __aenter__(self) -> Mock:
        return self.client

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class TestGetPersonIdRangesPageActivity:
    """Tests for get_person_id_ranges_page_activity's HogQL AST construction."""

    @pytest.mark.asyncio
    async def test_where_is_none_with_no_filters(self):
        captured: dict[str, object] = {}

        async def fake_compile(node, *, team_id):
            captured["node"] = node
            return "SELECT 1 FORMAT JSONEachRow", {}

        mock_client = Mock()
        mock_client.stream_query_as_jsonl = lambda *a, **kw: aiter([])

        with (
            patch(
                "posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow.compile_hogql_for_streaming",
                side_effect=fake_compile,
            ),
            patch(
                "posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow.get_client",
                return_value=_AsyncClientContextManager(mock_client),
            ),
            patch("temporalio.activity.heartbeat"),
        ):
            await get_person_id_ranges_page_activity(
                PersonIdRangesPageInputs(team_id=1, batch_size=10, page_size=5, after_person_id=None)
            )

        assert "node" in captured
        node = captured["node"]
        assert isinstance(node, ast.SelectQuery)
        assert node.where is None
        # Pagination must enumerate IDs off the raw ``person`` table with DISTINCT, not the
        # ``persons`` lazy table -- otherwise ``id > cursor`` is wrapped in an unbounded
        # ``id IN (...)`` subquery that GROUP BYs the whole ID tail on every page.
        assert node.distinct is True
        assert isinstance(node.select_from, ast.JoinExpr)
        assert isinstance(node.select_from.table, ast.Field)
        assert node.select_from.table.chain == ["raw_persons"]

    @pytest.mark.asyncio
    async def test_where_is_single_expr_with_only_after_person_id(self):
        captured: dict[str, object] = {}

        async def fake_compile(node, *, team_id):
            captured["node"] = node
            return "SELECT 1 FORMAT JSONEachRow", {}

        mock_client = Mock()
        mock_client.stream_query_as_jsonl = lambda *a, **kw: aiter([])

        with (
            patch(
                "posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow.compile_hogql_for_streaming",
                side_effect=fake_compile,
            ),
            patch(
                "posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow.get_client",
                return_value=_AsyncClientContextManager(mock_client),
            ),
            patch("temporalio.activity.heartbeat"),
        ):
            await get_person_id_ranges_page_activity(
                PersonIdRangesPageInputs(team_id=1, batch_size=10, page_size=5, after_person_id="abc-123")
            )

        assert "node" in captured
        node = captured["node"]
        assert isinstance(node, ast.SelectQuery)
        assert isinstance(node.where, ast.CompareOperation)
        assert node.where.op == ast.CompareOperationOp.Gt

    @pytest.mark.asyncio
    async def test_where_is_and_with_both_filters(self):
        captured: dict[str, object] = {}

        async def fake_compile(node, *, team_id):
            captured["node"] = node
            return "SELECT 1 FORMAT JSONEachRow", {}

        mock_client = Mock()
        mock_client.stream_query_as_jsonl = lambda *a, **kw: aiter([])

        with (
            patch(
                "posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow.compile_hogql_for_streaming",
                side_effect=fake_compile,
            ),
            patch(
                "posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow.get_client",
                return_value=_AsyncClientContextManager(mock_client),
            ),
            patch("temporalio.activity.heartbeat"),
        ):
            await get_person_id_ranges_page_activity(
                PersonIdRangesPageInputs(
                    team_id=1, batch_size=10, page_size=5, after_person_id="abc-123", person_id="def-456"
                )
            )

        assert "node" in captured
        node = captured["node"]
        assert isinstance(node, ast.SelectQuery)
        assert isinstance(node.where, ast.And)
        assert len(node.where.exprs) == 2
        ops = {e.op for e in node.where.exprs if isinstance(e, ast.CompareOperation)}
        assert ast.CompareOperationOp.Gt in ops
        assert ast.CompareOperationOp.Eq in ops


class TestPageActivityRowConsumption:
    """Stream real rows through get_person_id_ranges_page_activity.

    The AST tests above stream zero rows, so the row-consumption code — which reads ``row["person_id"]``
    and batches IDs into ranges — was never exercised. These feed real rows through it.
    """

    @pytest.mark.asyncio
    async def test_rows_batched_into_ranges(self):
        rows = [{"person_id": f"p{i}"} for i in range(1, 5)]
        mock_client = Mock()
        mock_client.stream_query_as_jsonl = lambda *a, **kw: aiter(rows)
        module = "posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow"
        with (
            patch(f"{module}.compile_hogql_for_streaming", side_effect=lambda node, *, team_id: ("SELECT 1", {})),
            patch(f"{module}.get_client", return_value=_AsyncClientContextManager(mock_client)),
            patch("temporalio.activity.heartbeat"),
        ):
            result = await get_person_id_ranges_page_activity(
                PersonIdRangesPageInputs(team_id=1, batch_size=2, page_size=10, after_person_id=None)
            )
        assert result.ranges == [("p1", "p2"), ("p3", "p4")]
        assert result.cursor is None  # 4 rows < limit (20), no more data

    @pytest.mark.asyncio
    async def test_has_more_data_sets_cursor(self):
        # batch_size=2, page_size=1 -> limit=2; a 3rd (limit+1) row signals more data and sets the cursor.
        rows = [{"person_id": f"p{i}"} for i in range(1, 4)]
        mock_client = Mock()
        mock_client.stream_query_as_jsonl = lambda *a, **kw: aiter(rows)
        module = "posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow"
        with (
            patch(f"{module}.compile_hogql_for_streaming", side_effect=lambda node, *, team_id: ("SELECT 1", {})),
            patch(f"{module}.get_client", return_value=_AsyncClientContextManager(mock_client)),
            patch("temporalio.activity.heartbeat"),
        ):
            result = await get_person_id_ranges_page_activity(
                PersonIdRangesPageInputs(team_id=1, batch_size=2, page_size=1, after_person_id=None)
            )
        assert result.ranges == [("p1", "p2")]
        assert result.cursor == "p2"  # last processed ID, used as the next page's after_person_id


class TestDrainCompleted:
    """The coordinator surfaces child failures via _drain_completed -> ApplicationError.

    The workflow test patches asyncio.wait to (set(), set()), so the failure-counting branch was never
    hit. This exercises _drain_completed directly with a failing handle.
    """

    @pytest.mark.asyncio
    async def test_counts_completed_and_failed_and_removes_handles(self):
        class _Handle:
            def __init__(self, fail: bool) -> None:
                self._fail = fail

            def __await__(self):
                async def _coro():
                    if self._fail:
                        raise RuntimeError("child boom")
                    return None

                return _coro().__await__()

        ok = _Handle(fail=False)
        bad = _Handle(fail=True)
        handles = [ok, bad]

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()
        completed, failed = await workflow._drain_completed({ok, bad}, handles, Mock())  # type: ignore[arg-type]  # fake handles stand in for ChildWorkflowHandle

        assert completed == 1
        assert failed == 1
        assert handles == []  # both drained handles removed from the in-flight list
