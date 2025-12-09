import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings

import structlog
import temporalio
from pydantic import BaseModel
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.models.event.util import create_event
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.message_utils import extract_text_from_messages

from products.llm_analytics.backend.models.evaluations import Evaluation

logger = structlog.get_logger(__name__)

# Default model for LLM judge
DEFAULT_JUDGE_MODEL = "gpt-5-mini"


class BooleanEvalResult(BaseModel):
    """Structured output for boolean evaluation results"""

    reasoning: str
    verdict: bool


@dataclass
class RunEvaluationInputs:
    evaluation_id: str
    event_data: dict[str, Any]


@temporalio.activity.defn
async def fetch_evaluation_activity(inputs: RunEvaluationInputs) -> dict[str, Any]:
    """Fetch evaluation config from Postgres"""

    def _fetch():
        try:
            evaluation = Evaluation.objects.get(id=inputs.evaluation_id)
            return {
                "id": str(evaluation.id),
                "name": evaluation.name,
                "evaluation_type": evaluation.evaluation_type,
                "evaluation_config": evaluation.evaluation_config,
                "output_type": evaluation.output_type,
                "output_config": evaluation.output_config,
                "team_id": evaluation.team_id,
            }
        except Evaluation.DoesNotExist:
            logger.exception("Evaluation not found", evaluation_id=inputs.evaluation_id)
            raise ValueError(f"Evaluation {inputs.evaluation_id} not found")

    return await database_sync_to_async(_fetch)()


@temporalio.activity.defn
async def execute_llm_judge_activity(evaluation: dict[str, Any], event_data: dict[str, Any]) -> dict[str, Any]:
    """Execute LLM judge to evaluate the target event"""
    import openai

    if evaluation["evaluation_type"] != "llm_judge":
        raise ApplicationError(
            f"Unsupported evaluation type: {evaluation['evaluation_type']}",
            non_retryable=True,
        )

    evaluation_config = evaluation.get("evaluation_config", {})
    prompt = evaluation_config.get("prompt")
    if not prompt:
        raise ApplicationError("Missing prompt in evaluation_config", non_retryable=True)

    output_type = evaluation["output_type"]
    if output_type != "boolean":
        raise ApplicationError(
            f"Unsupported output type: {output_type}. Only 'boolean' is currently supported.",
            non_retryable=True,
        )

    # Build context from event
    event_type = event_data["event"]
    properties = event_data["properties"]

    # Extract input/output based on event type
    if event_type == "$ai_generation":
        # Check properties in order of preference
        input_raw = properties.get("$ai_input") or properties.get("$ai_input_state", "")
        # For output, check $ai_output_choices first (most common), then $ai_output
        output_raw = (
            properties.get("$ai_output_choices")
            or properties.get("$ai_output")
            or properties.get("$ai_output_state", "")
        )
    else:
        # For other event types, use generic approach
        input_raw = properties.get("$ai_input_state", "")
        output_raw = properties.get("$ai_output_state", "")

    # Extract readable text from message structures
    input_data = extract_text_from_messages(input_raw)
    output_data = extract_text_from_messages(output_raw)

    # Build judge prompt
    system_prompt = f"""You are an evaluator. Evaluate the following generation according to this criteria:

{prompt}

Provide a brief reasoning (1 sentence) and a boolean verdict (true/false)."""

    user_prompt = f"""Input: {input_data}

Output: {output_data}"""

    # Call OpenAI
    client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

    response = client.beta.chat.completions.parse(
        model=DEFAULT_JUDGE_MODEL,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        response_format=BooleanEvalResult,
    )

    # Parse structured output
    result = response.choices[0].message.parsed
    if result is None:
        logger.exception("LLM judge returned empty structured response", evaluation_id=evaluation["id"])
        raise ValueError(f"LLM judge returned empty structured response for evaluation {evaluation['id']}")

    # Extract token usage from response
    usage = response.usage
    return {
        "verdict": result.verdict,
        "reasoning": result.reasoning,
        "input_tokens": usage.prompt_tokens if usage else 0,
        "output_tokens": usage.completion_tokens if usage else 0,
        "total_tokens": usage.total_tokens if usage else 0,
    }


@temporalio.activity.defn
async def emit_evaluation_event_activity(
    evaluation: dict[str, Any],
    event_data: dict[str, Any],
    result: dict[str, Any],
    start_time: datetime,
) -> None:
    """Emit $ai_evaluation event to ClickHouse"""

    def _emit():
        try:
            team = Team.objects.get(id=event_data["team_id"])
        except Team.DoesNotExist:
            logger.exception("Team not found", team_id=event_data["team_id"])
            raise ValueError(f"Team {event_data['team_id']} not found")

        event_uuid = uuid.uuid4()
        properties = {
            "$ai_evaluation_id": evaluation["id"],
            "$ai_evaluation_name": evaluation["name"],
            "$ai_evaluation_model": DEFAULT_JUDGE_MODEL,
            "$ai_evaluation_start_time": start_time.isoformat(),
            "$ai_evaluation_result": result["verdict"],
            "$ai_evaluation_reasoning": result["reasoning"],
            "$ai_target_event_id": event_data["uuid"],
            "$ai_target_event_type": event_data["event"],
            "$ai_trace_id": event_data["properties"].get("$ai_trace_id"),
        }

        # Convert person_id string to UUID
        person_id = uuid.UUID(event_data["person_id"]) if event_data.get("person_id") else None

        # Use current time for when the evaluation actually happened
        event_timestamp = datetime.now(UTC)

        create_event(
            event_uuid=event_uuid,
            event="$ai_evaluation",
            team=team,
            distinct_id=event_data["distinct_id"],
            timestamp=event_timestamp,
            properties=properties,
            person_id=person_id,
        )

    await database_sync_to_async(_emit, thread_sensitive=False)()


@temporalio.activity.defn
async def emit_internal_telemetry_activity(
    evaluation: dict[str, Any],
    team_id: int,
    result: dict[str, Any],
) -> None:
    """Emit telemetry event to PostHog org for internal tracking"""
    from posthog.tasks.usage_report import get_ph_client

    def _emit_telemetry():
        team = Team.objects.get(id=team_id)
        organization_id = str(team.organization_id)

        ph_client = get_ph_client(sync_mode=True)
        ph_client.capture(
            distinct_id=f"org-{organization_id}",
            event="llm analytics evaluation executed",
            properties={
                "evaluation_id": evaluation["id"],
                "team_id": team_id,
                "model": DEFAULT_JUDGE_MODEL,
                "input_tokens": result.get("input_tokens", 0),
                "output_tokens": result.get("output_tokens", 0),
                "total_tokens": result.get("total_tokens", 0),
                "verdict": result["verdict"],
            },
            groups={"organization": organization_id, "instance": settings.SITE_URL},
        )
        ph_client.flush()

    await database_sync_to_async(_emit_telemetry, thread_sensitive=False)()


@temporalio.workflow.defn(name="run-evaluation")
class RunEvaluationWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunEvaluationInputs:
        return RunEvaluationInputs(
            evaluation_id=inputs[0],
            event_data=json.loads(inputs[1]),
        )

    @temporalio.workflow.run
    async def run(self, inputs: RunEvaluationInputs) -> dict[str, Any]:
        start_time = temporalio.workflow.now()
        evaluation = await temporalio.workflow.execute_activity(
            fetch_evaluation_activity,
            inputs,
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # Normalize event_data: ensure properties is a dict, not a string
        event_data = inputs.event_data.copy()
        if isinstance(event_data.get("properties"), str):
            event_data["properties"] = json.loads(event_data["properties"])

        # Activity 2: Execute LLM judge
        result = await temporalio.workflow.execute_activity(
            execute_llm_judge_activity,
            args=[evaluation, event_data],
            schedule_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # Activity 3: Emit evaluation event
        await temporalio.workflow.execute_activity(
            emit_evaluation_event_activity,
            args=[evaluation, event_data, result, start_time],
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # Activity 4: Emit internal telemetry (fire-and-forget)
        await temporalio.workflow.execute_activity(
            emit_internal_telemetry_activity,
            args=[evaluation, event_data["team_id"], result],
            schedule_to_close_timeout=timedelta(seconds=30),
        )

        return {"verdict": result["verdict"], "reasoning": result["reasoning"], "evaluation_id": evaluation["id"]}
