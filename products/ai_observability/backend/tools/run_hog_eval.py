from typing import Any, Literal

from pydantic import BaseModel, Field

from posthog.schema import AssistantTool

from posthog.hogql import ast

from posthog.hogql_queries.ai.ai_table_resolver import query_ai_events
from posthog.hogql_queries.ai.utils import HEAVY_COLUMN_NAMES, merge_heavy_properties
from posthog.sync import database_sync_to_async

from products.ai_observability.backend.hog import compile_ai_observability_hog
from products.ai_observability.backend.models.evaluation_configs import (
    TRACE_EVAL_DEFAULT_WINDOW_SECONDS,
    TRACE_EVAL_MAX_WINDOW_SECONDS,
    TRACE_EVAL_MIN_WINDOW_SECONDS,
)

from ee.hogai.tool import MaxTool

TOOL_DESCRIPTION = """Test Hog evaluation code against sample data from the last 7 days.

Returns compilation errors if the code is invalid, or pass/fail/error results for each sample.

Set `target` to match how the evaluation will run: `generation` samples individual generations,
`trace` samples whole traces and exposes trace-level globals. For traces, set `window_seconds`
to the evaluation's aggregation window so the preview matches online behavior.

Write new evaluations using these globals:
- `evaluation_events` (array): the events under evaluation — one generation for a generation
  target, all events of the trace for a trace target. Each item has `uuid`, `event`, `timestamp`,
  serialized `input` and `output`, readable `input_text` and `output_text`, and `properties`
  without large input, output, and tool payloads.
- `target` (object): the sampled unit's `type` ('generation' or 'trace'), `id`, `total_cost_usd`,
  and `total_latency_seconds`.

Saved evaluations can still use the generation-only compatibility globals `input`, `output`,
`properties`, and `event`, but do not use them in new source that should also work for traces.

The code must return a boolean: `true` for pass, `false` for fail.
Use `print()` statements to output reasoning.
"""


class RunHogEvalTestArgs(BaseModel):
    source: str = Field(description="Hog evaluation source code to compile and test")
    sample_count: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Number of recent samples to test against (1-5)",
    )
    target: Literal["generation", "trace"] = Field(
        default="generation",
        description="What to sample: 'generation' (individual generations) or 'trace' (whole traces)",
    )
    window_seconds: int = Field(
        default=TRACE_EVAL_DEFAULT_WINDOW_SECONDS,
        ge=TRACE_EVAL_MIN_WINDOW_SECONDS,
        le=TRACE_EVAL_MAX_WINDOW_SECONDS,
        description="Aggregation window for trace samples, in seconds",
    )


class RunHogEvalTestTool(MaxTool):
    name: str = AssistantTool.RUN_HOG_EVAL_TEST.value
    description: str = TOOL_DESCRIPTION
    args_schema: type[BaseModel] = RunHogEvalTestArgs

    def get_required_resource_access(self):
        return [("llm_analytics", "viewer")]

    async def _arun_impl(
        self,
        source: str,
        sample_count: int = 3,
        target: Literal["generation", "trace"] = "generation",
        window_seconds: int = TRACE_EVAL_DEFAULT_WINDOW_SECONDS,
    ) -> tuple[str, Any]:
        from posthog.temporal.ai_observability.message_utils import extract_text_from_messages
        from posthog.temporal.ai_observability.run_evaluation import run_hog_eval

        try:
            bytecode = compile_ai_observability_hog(source, "destination")
        except Exception as e:
            return (f"Compilation error: {e}", None)

        team = self._team

        if target == "trace":
            return await self._run_over_traces(bytecode, sample_count, window_seconds)

        # Read from ai_events with native heavy columns so the Hog body still
        # sees `event.properties.$ai_input` etc. Falls back to the events table
        # when ai_events returns nothing (data beyond the retention window).
        query = ast.SelectQuery(
            select=[
                ast.Field(chain=["uuid"]),
                ast.Field(chain=["event"]),
                ast.Field(chain=["properties"]),
                ast.Field(chain=["distinct_id"]),
                ast.Field(chain=["timestamp"]),
                *[ast.Field(chain=[col]) for col in HEAVY_COLUMN_NAMES],
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["posthog", "ai_events"]), alias="ai_events"),
            where=ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.In,
                        left=ast.Field(chain=["event"]),
                        right=ast.Constant(value=["$ai_generation", "$ai_metric"]),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Gt,
                        left=ast.Field(chain=["timestamp"]),
                        right=ast.ArithmeticOperation(
                            op=ast.ArithmeticOperationOp.Sub,
                            left=ast.Call(name="now", args=[]),
                            right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=7)]),
                        ),
                    ),
                ]
            ),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
            limit=ast.Constant(value=sample_count),
        )

        response = await database_sync_to_async(query_ai_events)(
            query=query,
            placeholders={},
            team=team,
            query_type="RunHogEvalTest",
            fall_back_to_events=True,
        )
        if not response.results:
            return (
                "No recent AI events found in the last 7 days. Ingest some $ai_generation or $ai_metric events first.",
                None,
            )

        # Parse all events first to collect property keys and build event data.
        # Heavy columns trail the five base columns in row order — re-merge them
        # into `properties` so the Hog body can read `properties.$ai_input` etc.
        # `merge_heavy_properties` skips NULL heavy slots, so on the events
        # fallback (heavy columns absent) it re-merges nothing, and on ai_events
        # it fills `properties.$ai_*` from the native columns.
        parsed_events: list[dict[str, Any]] = []
        all_property_keys: set[str] = set()
        for row in response.results:
            heavy_values = row[5 : 5 + len(HEAVY_COLUMN_NAMES)]
            heavy_columns = dict(zip(HEAVY_COLUMN_NAMES, heavy_values))
            properties = merge_heavy_properties(row[2], heavy_columns)
            all_property_keys.update(properties.keys())
            parsed_events.append(
                {
                    "uuid": str(row[0]),
                    "event": row[1],
                    "properties": properties,
                    "distinct_id": row[3] or "",
                    "timestamp": row[4],
                }
            )

        # Build a data summary so the LLM understands the event shape
        ai_keys = sorted(k for k in all_property_keys if k.startswith("$ai_"))
        other_keys = sorted(k for k in all_property_keys if not k.startswith("$ai_"))
        lines: list[str] = [
            f"Sampled {len(parsed_events)} event(s). Available properties on these events:",
            f"  AI properties: {', '.join(ai_keys) if ai_keys else '(none)'}",
            f"  Other properties: {', '.join(other_keys[:20])}" + (" ..." if len(other_keys) > 20 else ""),
        ]

        # Show a sample of key AI property values from the first event for context
        first_props = parsed_events[0]["properties"]
        if first_props.get("$ai_model"):
            lines.append(f"  Sample $ai_model: {first_props['$ai_model']}")
        if first_props.get("$ai_provider"):
            lines.append(f"  Sample $ai_provider: {first_props['$ai_provider']}")
        lines.append("")

        # Run eval against each event
        for event_data in parsed_events:
            properties = event_data["properties"]
            event_type = event_data["event"]

            result = run_hog_eval(bytecode, event_data, allows_na=True)

            if event_type == "$ai_generation":
                input_raw = properties.get("$ai_input") or properties.get("$ai_input_state", "")
                output_raw = (
                    properties.get("$ai_output_choices")
                    or properties.get("$ai_output")
                    or properties.get("$ai_output_state", "")
                )
            else:
                input_raw = properties.get("$ai_input_state", "")
                output_raw = properties.get("$ai_output_state", "")

            input_preview = extract_text_from_messages(input_raw)[:200]
            output_preview = extract_text_from_messages(output_raw)[:200]

            verdict = result["verdict"]
            if result["error"]:
                verdict_str = "ERROR"
            elif verdict is True:
                verdict_str = "PASS"
            elif verdict is False:
                verdict_str = "FAIL"
            else:
                verdict_str = "N/A"

            lines.append(f"Event {event_data['uuid']} ({event_type}):")
            lines.append(f"  Input:  {input_preview}")
            lines.append(f"  Output: {output_preview}")
            lines.append(f"  Result: {verdict_str}")
            if result["reasoning"]:
                lines.append(f"  Reasoning: {result['reasoning']}")
            if result["error"]:
                lines.append(f"  Error: {result['error']}")
            lines.append("")

        return ("\n".join(lines), None)

    async def _run_over_traces(self, bytecode: list[Any], sample_count: int, window_seconds: int) -> tuple[str, Any]:
        from posthog.temporal.ai_observability.run_trace_evaluation import run_hog_eval_over_recent_traces

        trace_results = await database_sync_to_async(run_hog_eval_over_recent_traces)(
            team=self._team,
            bytecode=bytecode,
            condition_filter=None,
            sample_count=sample_count,
            allows_na=True,
            window_seconds=window_seconds,
        )
        if not trace_results:
            return ("No recent AI traces found in the last 7 days. Ingest some $ai_generation events first.", None)

        lines: list[str] = [f"Sampled {len(trace_results)} trace(s). Ran against trace-level globals.", ""]
        for r in trace_results:
            if r.error:
                verdict_str = "ERROR"
            elif r.verdict is True:
                verdict_str = "PASS"
            elif r.verdict is False:
                verdict_str = "FAIL"
            else:
                verdict_str = "N/A"

            lines.append(f"Trace {r.trace_id}:")
            lines.append(f"  Input:  {r.input_preview}")
            lines.append(f"  Output: {r.output_preview}")
            lines.append(f"  Result: {verdict_str}")
            if r.reasoning:
                lines.append(f"  Reasoning: {r.reasoning}")
            if r.error:
                lines.append(f"  Error: {r.error}")
            lines.append("")

        return ("\n".join(lines), None)
