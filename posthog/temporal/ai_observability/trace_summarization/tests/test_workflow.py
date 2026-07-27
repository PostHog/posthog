"""Tests for batch trace summarization workflow and sampling."""

from contextlib import asynccontextmanager

import pytest
from unittest.mock import patch

from posthog.hogql.context import HogQLContext
from posthog.hogql.placeholders import replace_placeholders
from posthog.hogql.printer.utils import prepare_and_print_ast

from posthog.sync import database_sync_to_async
from posthog.temporal.ai_observability.trace_summarization.models import BatchSummarizationInputs, SampledItem
from posthog.temporal.ai_observability.trace_summarization.sampling import sample_items_in_window_activity
from posthog.temporal.ai_observability.trace_summarization.workflow import BatchTraceSummarizationWorkflow


@asynccontextmanager
async def _noop_heartbeater(*args, **kwargs):
    yield


@pytest.fixture
def mock_team(db):
    from posthog.models.organization import Organization
    from posthog.models.team import Team

    organization = Organization.objects.create(name="Test Org")
    team = Team.objects.create(
        organization=organization,
        name="Test Team",
    )
    return team


@patch(
    "posthog.temporal.ai_observability.trace_summarization.sampling.Heartbeater",
    _noop_heartbeater,
)
class TestSampleItemsInWindowActivity:
    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_sample_traces_success(self, mock_team):
        inputs = BatchSummarizationInputs(
            team_id=mock_team.id,
            max_items=100,
            window_minutes=60,
            window_start="2025-01-15T11:00:00",
            window_end="2025-01-15T12:00:00",
        )

        mock_results = [[f"trace_{i}", f"2025-01-15T11:{i:02d}:00+00:00"] for i in range(50)]

        with patch(
            "posthog.temporal.ai_observability.trace_summarization.sampling.execute_hogql_query"
        ) as mock_execute:
            mock_execute.return_value.results = mock_results

            result = await sample_items_in_window_activity(inputs)

            assert len(result) == 50
            assert isinstance(result[0], SampledItem)
            assert result[0].trace_id == "trace_0"
            assert result[0].generation_id is None
            assert result[49].trace_id == "trace_49"

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_sample_traces_passes_size_filter(self, mock_team):
        from posthog.temporal.ai_observability.trace_summarization.constants import (
            MAX_TRACE_EVENTS_LIMIT,
            MAX_TRACE_PROPERTIES_SIZE,
        )

        inputs = BatchSummarizationInputs(
            team_id=mock_team.id,
            max_items=10,
            window_minutes=60,
            window_start="2025-01-15T11:00:00",
            window_end="2025-01-15T12:00:00",
        )

        with patch(
            "posthog.temporal.ai_observability.trace_summarization.sampling.execute_hogql_query"
        ) as mock_execute:
            mock_execute.return_value.results = []

            await sample_items_in_window_activity(inputs)

            placeholders = mock_execute.call_args.kwargs["placeholders"]
            assert placeholders["max_events"].value == MAX_TRACE_EVENTS_LIMIT
            assert placeholders["max_properties_size"].value == MAX_TRACE_PROPERTIES_SIZE

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_sample_generations_success(self, mock_team):
        inputs = BatchSummarizationInputs(
            team_id=mock_team.id,
            max_items=50,
            analysis_level="generation",
            window_minutes=60,
            window_start="2025-01-15T11:00:00",
            window_end="2025-01-15T12:00:00",
        )

        mock_results = [[f"trace_{i}", f"gen-uuid-{i}", f"2025-01-15T11:{i:02d}:00+00:00"] for i in range(10)]

        with patch(
            "posthog.temporal.ai_observability.trace_summarization.sampling.execute_hogql_query"
        ) as mock_execute:
            mock_execute.return_value.results = mock_results

            result = await sample_items_in_window_activity(inputs)

            assert len(result) == 10
            assert isinstance(result[0], SampledItem)
            assert result[0].trace_id == "trace_0"
            assert result[0].generation_id == "gen-uuid-0"

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_sample_generations_passes_size_filter(self, mock_team):
        from posthog.temporal.ai_observability.trace_summarization.constants import (
            MAX_TRACE_EVENTS_LIMIT,
            MAX_TRACE_PROPERTIES_SIZE,
        )

        inputs = BatchSummarizationInputs(
            team_id=mock_team.id,
            max_items=50,
            analysis_level="generation",
            window_minutes=60,
            window_start="2025-01-15T11:00:00",
            window_end="2025-01-15T12:00:00",
        )

        with patch(
            "posthog.temporal.ai_observability.trace_summarization.sampling.execute_hogql_query"
        ) as mock_execute:
            mock_execute.return_value.results = []

            await sample_items_in_window_activity(inputs)

            placeholders = mock_execute.call_args.kwargs["placeholders"]
            assert placeholders["max_events"].value == MAX_TRACE_EVENTS_LIMIT
            assert placeholders["max_properties_size"].value == MAX_TRACE_PROPERTIES_SIZE

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_generation_filter_is_applied_inside_argmaxif(self, mock_team):
        from posthog.hogql import ast
        from posthog.hogql.visitor import TraversingVisitor

        inputs = BatchSummarizationInputs(
            team_id=mock_team.id,
            max_items=10,
            analysis_level="generation",
            window_minutes=60,
            window_start="2025-01-15T11:00:00",
            window_end="2025-01-15T12:00:00",
            event_filters=[{"key": "is_background_task", "type": "event", "value": ["false"], "operator": "exact"}],
        )

        with patch(
            "posthog.temporal.ai_observability.trace_summarization.sampling.execute_hogql_query"
        ) as mock_execute:
            mock_execute.return_value.results = []
            await sample_items_in_window_activity(inputs)

            query: ast.SelectQuery = mock_execute.call_args.kwargs["query"]

            class CallCollector(TraversingVisitor):
                def __init__(self, name: str) -> None:
                    self.name = name
                    self.found: list[ast.Call] = []

                def visit_call(self, node: ast.Call) -> None:
                    if node.name == self.name:
                        self.found.append(node)
                    super().visit_call(node)

            class KeyReferenced(TraversingVisitor):
                def __init__(self, key: str) -> None:
                    self.key = key
                    self.found = False

                def visit_field(self, node: ast.Field) -> None:
                    if node.chain and node.chain[-1] == self.key:
                        self.found = True

            argmaxif = CallCollector("argMaxIf")
            for item in query.select:
                argmaxif.visit(item)
            assert len(argmaxif.found) == 1

            class PlaceholderFinder(TraversingVisitor):
                def __init__(self, name: str) -> None:
                    self.name = name
                    self.found = False

                def visit_placeholder(self, node: ast.Placeholder) -> None:
                    if node.chain and node.chain[-1] == self.name:
                        self.found = True

            trace_filter_in_argmaxif = PlaceholderFinder("trace_filter")
            trace_filter_in_argmaxif.visit(argmaxif.found[0].args[2])
            assert trace_filter_in_argmaxif.found, (
                "Filter placeholder must be inside argMaxIf so the picked generation itself satisfies it"
            )

            trace_filter_expr = mock_execute.call_args.kwargs["placeholders"]["trace_filter"]
            key_ref = KeyReferenced("is_background_task")
            key_ref.visit(trace_filter_expr)
            assert key_ref.found, "trace_filter placeholder must reference the configured event property"

            # The trace-level countIf gate is redundant once the filter is in argMaxIf —
            # HAVING drops traces whose argMaxIf returned the zero UUID (no matching generation).
            countif = CallCollector("countIf")
            if query.having is not None:
                countif.visit(query.having)
            assert countif.found == []

            # argMaxIf with no matching rows returns the zero UUID (not NULL), so
            # HAVING must explicitly compare against it — IS NOT NULL doesn't catch it.
            # toUUIDOrZero is not whitelisted; toUUID('...') is (constant-folded UUID compare).
            assert query.having is not None
            to_uuid_guard = CallCollector("toUUID")
            to_uuid_guard.visit(query.having)
            assert to_uuid_guard.found, "HAVING must guard against zero-UUID phantom generations"

            class ConstantFinder(TraversingVisitor):
                def __init__(self, value: str) -> None:
                    self.value = value
                    self.found = False

                def visit_constant(self, node: ast.Constant) -> None:
                    if node.value == self.value:
                        self.found = True

            zero_uuid_literal = ConstantFinder("00000000-0000-0000-0000-000000000000")
            zero_uuid_literal.visit(query.having)
            assert zero_uuid_literal.found, "HAVING must compare against the literal zero UUID"

            # Validate the query against the real HogQL printer — every function call
            # must be in the allowlist. Without this, a regression like toUUIDOrZero
            # (rejected at runtime as `QueryError: Unsupported function call`) ships.
            # Wrapped in database_sync_to_async because the printer loads the team
            # via the Django ORM, which is blocked from this async test context.
            placeholders = mock_execute.call_args.kwargs["placeholders"]
            materialized = replace_placeholders(query, placeholders)
            await database_sync_to_async(prepare_and_print_ast, thread_sensitive=False)(
                materialized,
                HogQLContext(team_id=mock_team.id, enable_select_queries=True),
                "clickhouse",
            )

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_sample_items_empty(self, mock_team):
        inputs = BatchSummarizationInputs(
            team_id=mock_team.id,
            max_items=100,
            window_minutes=60,
            window_start="2025-01-15T11:00:00",
            window_end="2025-01-15T12:00:00",
        )

        with patch(
            "posthog.temporal.ai_observability.trace_summarization.sampling.execute_hogql_query"
        ) as mock_execute:
            mock_execute.return_value.results = []

            result = await sample_items_in_window_activity(inputs)

            assert len(result) == 0

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_sample_skips_when_cohort_filter_references_missing_cohort(self, mock_team):
        # Cohort referenced by a saved job was deleted between save and run.
        # Activity should log + return [] rather than raise.
        inputs = BatchSummarizationInputs(
            team_id=mock_team.id,
            max_items=100,
            window_minutes=60,
            window_start="2025-01-15T11:00:00",
            window_end="2025-01-15T12:00:00",
            event_filters=[{"key": "id", "value": 999_999, "type": "cohort"}],
        )

        with patch(
            "posthog.temporal.ai_observability.trace_summarization.sampling.execute_hogql_query"
        ) as mock_execute:
            result = await sample_items_in_window_activity(inputs)

            assert result == []
            mock_execute.assert_not_called()

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_sample_skips_when_cohort_filter_references_soft_deleted_cohort(self, mock_team):
        from asgiref.sync import sync_to_async

        from products.cohorts.backend.models.cohort import Cohort

        cohort = await sync_to_async(Cohort.objects.create)(team=mock_team, name="Stale", deleted=True)
        inputs = BatchSummarizationInputs(
            team_id=mock_team.id,
            max_items=100,
            window_minutes=60,
            window_start="2025-01-15T11:00:00",
            window_end="2025-01-15T12:00:00",
            event_filters=[{"key": "id", "value": cohort.id, "type": "cohort"}],
        )

        with patch(
            "posthog.temporal.ai_observability.trace_summarization.sampling.execute_hogql_query"
        ) as mock_execute:
            result = await sample_items_in_window_activity(inputs)

            assert result == []
            mock_execute.assert_not_called()

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_sample_runs_when_cohort_filter_resolves(self, mock_team):
        from asgiref.sync import sync_to_async

        from products.cohorts.backend.models.cohort import Cohort

        cohort = await sync_to_async(Cohort.objects.create)(team=mock_team, name="VIPs")
        inputs = BatchSummarizationInputs(
            team_id=mock_team.id,
            max_items=100,
            window_minutes=60,
            window_start="2025-01-15T11:00:00",
            window_end="2025-01-15T12:00:00",
            event_filters=[{"key": "id", "value": cohort.id, "type": "cohort"}],
        )

        with patch(
            "posthog.temporal.ai_observability.trace_summarization.sampling.execute_hogql_query"
        ) as mock_execute:
            mock_execute.return_value.results = []

            result = await sample_items_in_window_activity(inputs)

            assert result == []
            mock_execute.assert_called_once()


class TestBatchTraceSummarizationWorkflow:
    def test_parse_inputs_minimal(self):
        inputs = BatchTraceSummarizationWorkflow.parse_inputs(["123"])

        assert inputs.team_id == 123
        assert inputs.analysis_level == "trace"
        assert inputs.max_items == 15
        assert inputs.batch_size == 10
        assert inputs.mode == "detailed"
        assert inputs.window_minutes == 60

    def test_parse_inputs_full_trace_level(self):
        inputs = BatchTraceSummarizationWorkflow.parse_inputs(
            ["123", "trace", "200", "20", "detailed", "30", "2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z"]
        )

        assert inputs.team_id == 123
        assert inputs.analysis_level == "trace"
        assert inputs.max_items == 200
        assert inputs.batch_size == 20
        assert inputs.mode == "detailed"
        assert inputs.window_minutes == 30
        assert inputs.window_start == "2025-01-01T00:00:00Z"
        assert inputs.window_end == "2025-01-02T00:00:00Z"

    def test_parse_inputs_full_generation_level(self):
        inputs = BatchTraceSummarizationWorkflow.parse_inputs(
            ["123", "generation", "200", "20", "detailed", "30", "2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z"]
        )

        assert inputs.team_id == 123
        assert inputs.analysis_level == "generation"
        assert inputs.max_items == 200
        assert inputs.batch_size == 20
        assert inputs.mode == "detailed"
        assert inputs.window_minutes == 30
        assert inputs.window_start == "2025-01-01T00:00:00Z"
        assert inputs.window_end == "2025-01-02T00:00:00Z"
