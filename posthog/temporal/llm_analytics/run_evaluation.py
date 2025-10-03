import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings

import structlog
import temporalio
from temporalio.common import RetryPolicy

from posthog.clickhouse.client import sync_execute
from posthog.models.event.util import create_event
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.message_utils import extract_text_from_messages

from products.llm_analytics.backend.models.evaluations import Evaluation

logger = structlog.get_logger(__name__)

# Default model for LLM judge
DEFAULT_JUDGE_MODEL = "gpt-4"


@dataclass
class RunEvaluationInputs:
    evaluation_id: str
    target_event_id: str


@temporalio.activity.defn
async def fetch_target_event_activity(inputs: RunEvaluationInputs) -> dict[str, Any]:
    """Fetch target event from ClickHouse"""
    logger.info(
        "Fetching target event",
        evaluation_id=inputs.evaluation_id,
        target_event_id=inputs.target_event_id,
    )

    query = """
        SELECT
            uuid,
            event,
            properties,
            timestamp,
            team_id,
            distinct_id,
            person_id
        FROM events
        WHERE uuid = %(event_id)s
        LIMIT 1
    """

    result = await database_sync_to_async(sync_execute, thread_sensitive=False)(
        query, {"event_id": inputs.target_event_id}
    )

    if not result:
        logger.error("Event not found", target_event_id=inputs.target_event_id)
        raise ValueError(f"Event {inputs.target_event_id} not found")

    row = result[0]
    event_data = {
        "uuid": str(row[0]),
        "event": row[1],
        "properties": json.loads(row[2]) if isinstance(row[2], str) else row[2],
        "timestamp": row[3],
        "team_id": row[4],
        "distinct_id": row[5],
        "person_id": str(row[6]),
    }
    logger.info(
        "Target event fetched successfully",
        event_uuid=event_data["uuid"],
        event_type=event_data["event"],
        team_id=event_data["team_id"],
        distinct_id=event_data["distinct_id"],
        person_id=event_data["person_id"],
        timestamp=event_data["timestamp"],
    )
    return event_data


@temporalio.activity.defn
async def fetch_evaluation_activity(inputs: RunEvaluationInputs) -> dict[str, Any]:
    """Fetch evaluation config from Postgres"""
    logger.info("Fetching evaluation config", evaluation_id=inputs.evaluation_id)

    def _fetch():
        evaluation = Evaluation.objects.get(id=inputs.evaluation_id)
        logger.info("Evaluation fetched", evaluation_id=str(evaluation.id), name=evaluation.name)
        return {
            "id": str(evaluation.id),
            "name": evaluation.name,
            "prompt": evaluation.prompt,
            "team_id": evaluation.team_id,
        }

    return await database_sync_to_async(_fetch)()


@temporalio.activity.defn
async def execute_llm_judge_activity(evaluation: dict[str, Any], event_data: dict[str, Any]) -> dict[str, Any]:
    """Execute LLM judge to evaluate the target event"""
    logger.info(
        "Executing LLM judge",
        evaluation_id=evaluation["id"],
        evaluation_name=evaluation["name"],
        target_event_id=event_data["uuid"],
    )

    import openai

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
    system_prompt = f"""You are an AI evaluator. Evaluate the following AI generation according to this criteria:

{evaluation["prompt"]}

Respond with ONLY a JSON object in this exact format:
{{
  "reasoning": "Brief explanation of your evaluation (1 sentence)",
  "verdict": true
}}

or

{{
  "reasoning": "Brief explanation of your evaluation (1 sentence)",
  "verdict": false
}}

Do not include any other text, explanation, or formatting outside the JSON object."""

    user_prompt = f"""Input: {input_data}

Output: {output_data}"""

    # Call OpenAI
    client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

    response = client.chat.completions.create(
        model=DEFAULT_JUDGE_MODEL,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        temperature=0.0,
        max_tokens=500,
    )

    # Parse response
    content = response.choices[0].message.content
    try:
        result = json.loads(content)
        verdict = bool(result.get("verdict", False))
        reasoning = result.get("reasoning", "No reasoning provided")
        logger.info(
            "LLM judge completed",
            evaluation_id=evaluation["id"],
            verdict=verdict,
            reasoning=reasoning,
            target_event_id=event_data["uuid"],
        )
        return {"verdict": verdict, "reasoning": reasoning}
    except (json.JSONDecodeError, KeyError) as e:
        logger.exception(
            "Failed to parse LLM judge response", response=content, evaluation_id=evaluation["id"], error=str(e)
        )
        # Default to False on parse error
        return {"verdict": False, "reasoning": f"Failed to parse LLM response: {content[:200]}"}


@temporalio.activity.defn
async def emit_evaluation_event_activity(
    evaluation: dict[str, Any],
    event_data: dict[str, Any],
    result: dict[str, Any],
    start_time: datetime,
) -> None:
    """Emit $ai_evaluation event to ClickHouse"""

    def _emit():
        team = Team.objects.get(id=event_data["team_id"])

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

        logger.info(
            "Creating evaluation event",
            evaluation_event_uuid=str(event_uuid),
            team_id=team.id,
            project_id=team.project_id,
            distinct_id=event_data["distinct_id"],
            person_id=str(person_id) if person_id else None,
            timestamp=event_timestamp,
            target_event_uuid=event_data["uuid"],
            evaluation_id=evaluation["id"],
            verdict=result["verdict"],
            reasoning=result["reasoning"][:100],
        )

        create_event(
            event_uuid=event_uuid,
            event="$ai_evaluation",
            team=team,
            distinct_id=event_data["distinct_id"],
            timestamp=event_timestamp,
            properties=properties,
            person_id=person_id,
        )

        logger.info(
            "Emitted evaluation event successfully",
            evaluation_event_uuid=str(event_uuid),
            evaluation_id=evaluation["id"],
            target_event_id=event_data["uuid"],
            verdict=result["verdict"],
        )

    await database_sync_to_async(_emit, thread_sensitive=False)()


@temporalio.workflow.defn(name="run-evaluation")
class RunEvaluationWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunEvaluationInputs:
        return RunEvaluationInputs(
            evaluation_id=inputs[0],
            target_event_id=inputs[1],
        )

    @temporalio.workflow.run
    async def run(self, inputs: RunEvaluationInputs) -> dict[str, Any]:
        start_time = temporalio.workflow.now()

        # Activity 1: Fetch target event
        event_data = await temporalio.workflow.execute_activity(
            fetch_target_event_activity,
            inputs,
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # Activity 2: Fetch evaluation config
        evaluation = await temporalio.workflow.execute_activity(
            fetch_evaluation_activity,
            inputs,
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # Verify team_id matches
        if event_data["team_id"] != evaluation["team_id"]:
            raise ValueError(
                f"Team mismatch: event team_id={event_data['team_id']}, evaluation team_id={evaluation['team_id']}"
            )

        # Activity 3: Execute LLM judge
        result = await temporalio.workflow.execute_activity(
            execute_llm_judge_activity,
            args=[evaluation, event_data],
            schedule_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # Activity 4: Emit evaluation event
        await temporalio.workflow.execute_activity(
            emit_evaluation_event_activity,
            args=[evaluation, event_data, result, start_time],
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        return {"verdict": result["verdict"], "reasoning": result["reasoning"], "evaluation_id": evaluation["id"]}
