import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.hogql import ast

from posthog.temporal.data_imports.signals.registry import SignalEmitterOutput, SignalSourceTableConfig
from posthog.temporal.data_imports.workflow_activities.emit_signals import (
    EmitDataImportSignalsWorkflow,
    EmitSignalsActivityInputs,
    _build_emitter_outputs,
    _check_actionability,
    _emit_signals,
    _filter_actionable,
    _query_new_records,
)

MODULE_PATH = "posthog.temporal.data_imports.workflow_activities.emit_signals"


def _make_config(**overrides: Any) -> SignalSourceTableConfig:
    defaults: dict[str, Any] = {
        "emitter": lambda team_id, record: SignalEmitterOutput(
            source_type="test",
            source_id=str(record.get("id", "unknown")),
            description=record.get("description", ""),
            weight=0.5,
            extra=record,
        ),
        "partition_field": "created_at",
        "fields": ("id", "description"),
    }
    return SignalSourceTableConfig(**(defaults | overrides))


def _make_output(source_id: str = "1", description: str = "test signal") -> SignalEmitterOutput:
    return SignalEmitterOutput(
        source_type="test",
        source_id=source_id,
        description=description,
        weight=0.5,
        extra={},
    )


class TestQueryNewRecords:
    def test_continuous_sync_uses_partition_field_and_placeholders(self):
        config = _make_config(partition_field="updated_at")
        mock_result = MagicMock()
        mock_result.columns = ["id", "name"]
        mock_result.results = [(1, "alice")]

        with patch(f"{MODULE_PATH}.execute_hogql_query", return_value=mock_result):
            with patch(f"{MODULE_PATH}.parse_select", return_value="parsed") as mock_parse:
                records = _query_new_records(
                    team=MagicMock(),
                    table_name="test_table",
                    last_synced_at="2025-01-01T00:00:00Z",
                    config=config,
                    extra={},
                )

        query_arg = mock_parse.call_args[0][0]
        assert "updated_at > {last_synced_at}" in query_arg
        assert mock_parse.call_args.kwargs["placeholders"]["last_synced_at"] == ast.Constant(
            value=datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
        )
        assert records == [{"id": 1, "name": "alice"}]

    def test_first_sync_uses_lookback_window(self):
        config = _make_config(partition_field="time", first_sync_lookback_days=14)
        mock_result = MagicMock()
        mock_result.results = []
        mock_result.columns = []

        with patch(f"{MODULE_PATH}.execute_hogql_query", return_value=mock_result):
            with patch(f"{MODULE_PATH}.parse_select", return_value="parsed") as mock_parse:
                _query_new_records(
                    team=MagicMock(),
                    table_name="test_table",
                    last_synced_at=None,
                    config=config,
                    extra={},
                )

        query_arg = mock_parse.call_args[0][0]
        assert "time > now() - interval 14 day" in query_arg
        assert "placeholders" not in mock_parse.call_args.kwargs

    def test_returns_empty_on_query_error(self):
        config = _make_config()

        with (
            patch(f"{MODULE_PATH}.execute_hogql_query", side_effect=Exception("query failed")),
            patch(f"{MODULE_PATH}.parse_select", return_value="parsed"),
            patch(f"{MODULE_PATH}.activity"),
        ):
            records = _query_new_records(
                team=MagicMock(),
                table_name="test_table",
                last_synced_at="2025-01-01T00:00:00Z",
                config=config,
                extra={},
            )

        assert records == []


class TestBuildEmitterOutputs:
    def test_filters_out_none_results(self):
        def selective_emitter(team_id, record):
            if record.get("valid"):
                return _make_output(source_id=str(record["id"]))
            return None

        records = [{"id": 1, "valid": True}, {"id": 2, "valid": False}, {"id": 3, "valid": True}]
        outputs = _build_emitter_outputs(team_id=1, records=records, emitter=selective_emitter)

        assert [o.source_id for o in outputs] == ["1", "3"]


class TestCheckActionability:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "llm_response,expected",
        [
            ("ACTIONABLE", True),
            ("NOT_ACTIONABLE", False),
            ("actionable", True),
            ("This is NOT_ACTIONABLE as it is just a billing question.", False),
        ],
    )
    async def test_classifies_based_on_llm_response(self, llm_response, expected):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = llm_response
        mock_client.models.generate_content = AsyncMock(return_value=mock_response)

        output = _make_output(description="test ticket")
        result = await _check_actionability(mock_client, output, "Is this actionable? {description}")

        assert result is expected

    @pytest.mark.asyncio
    async def test_returns_true_on_llm_error(self):
        mock_client = MagicMock()
        mock_client.models.generate_content = AsyncMock(side_effect=Exception("API error"))

        with patch(f"{MODULE_PATH}.posthoganalytics"):
            result = await _check_actionability(mock_client, _make_output(), "prompt {description}")

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_on_none_response_text(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = None
        mock_client.models.generate_content = AsyncMock(return_value=mock_response)

        result = await _check_actionability(mock_client, _make_output(), "prompt {description}")

        assert result is True


class TestFilterActionable:
    @pytest.mark.asyncio
    async def test_filters_non_actionable_outputs(self):
        outputs = [_make_output(source_id="1"), _make_output(source_id="2"), _make_output(source_id="3")]

        mock_client = MagicMock()
        responses = ["ACTIONABLE", "NOT_ACTIONABLE", "ACTIONABLE"]
        call_count = 0

        async def mock_generate(*args, **kwargs):
            nonlocal call_count
            resp = MagicMock()
            resp.text = responses[call_count]
            call_count += 1
            return resp

        mock_client.models.generate_content = mock_generate

        with (
            patch(f"{MODULE_PATH}.genai") as mock_genai,
            patch(f"{MODULE_PATH}.activity"),
        ):
            mock_genai.AsyncClient.return_value = mock_client
            result = await _filter_actionable(outputs, "prompt {description}", extra={})

        assert [o.source_id for o in result] == ["1", "3"]


class TestEmitSignals:
    @pytest.mark.asyncio
    async def test_passes_correct_args_to_emit_signal(self):
        output = _make_output(source_id="42", description="bug report")
        team = MagicMock()

        with (
            patch(f"{MODULE_PATH}.emit_signal", new_callable=AsyncMock) as mock_emit,
            patch(f"{MODULE_PATH}.activity"),
        ):
            count = await _emit_signals(team=team, outputs=[output], extra={})

        assert count == 1
        mock_emit.assert_called_once_with(
            team=team,
            source_product="data_imports",
            source_type="test",
            source_id="42",
            description="bug report",
            weight=0.5,
            extra={},
        )

    @pytest.mark.asyncio
    async def test_continues_on_individual_emit_failure(self):
        outputs = [_make_output(source_id="1"), _make_output(source_id="2"), _make_output(source_id="3")]
        call_count = 0

        async def mock_emit(**kwargs):
            nonlocal call_count
            call_count += 1
            if kwargs["source_id"] == "2":
                raise Exception("emit failed")

        with (
            patch(f"{MODULE_PATH}.emit_signal", side_effect=mock_emit),
            patch(f"{MODULE_PATH}.activity"),
        ):
            count = await _emit_signals(team=MagicMock(), outputs=outputs, extra={})

        assert count == 2
        assert call_count == 3


class TestEmitDataImportSignalsWorkflow:
    def test_parse_inputs(self):
        schema_id = str(uuid.uuid4())
        source_id = str(uuid.uuid4())
        raw = json.dumps(
            {
                "team_id": 1,
                "schema_id": schema_id,
                "source_id": source_id,
                "job_id": "job-123",
                "source_type": "Zendesk",
                "schema_name": "tickets",
                "last_synced_at": "2025-01-01T00:00:00Z",
            }
        )

        result = EmitDataImportSignalsWorkflow.parse_inputs([raw])

        assert result.team_id == 1
        assert str(result.schema_id) == schema_id
        assert result.source_type == "Zendesk"
        assert result.last_synced_at == "2025-01-01T00:00:00Z"

    @pytest.mark.asyncio
    async def test_executes_activity_with_inputs(self):
        schema_id = uuid.uuid4()
        source_id = uuid.uuid4()
        captured_inputs: dict[str, Any] = {}

        @activity.defn(name="emit_data_import_signals_activity")
        async def mock_activity(inputs: EmitSignalsActivityInputs) -> dict:
            captured_inputs["team_id"] = inputs.team_id
            captured_inputs["schema_id"] = inputs.schema_id
            captured_inputs["source_type"] = inputs.source_type
            return {"status": "success", "signals_emitted": 5}

        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[EmitDataImportSignalsWorkflow],
                activities=[mock_activity],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    EmitDataImportSignalsWorkflow.run,
                    EmitSignalsActivityInputs(
                        team_id=42,
                        schema_id=schema_id,
                        source_id=source_id,
                        job_id="job-abc",
                        source_type="Zendesk",
                        schema_name="tickets",
                        last_synced_at="2025-01-01T00:00:00Z",
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        assert captured_inputs["team_id"] == 42
        assert captured_inputs["schema_id"] == schema_id
        assert captured_inputs["source_type"] == "Zendesk"
