import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings

import structlog
import temporalio
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

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
    timestamp: str


@temporalio.activity.defn
async def fetch_target_event_activity(inputs: RunEvaluationInputs, team_id: int) -> dict[str, Any]:
    """Fetch target event from ClickHouse"""
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
        WHERE team_id = %(team_id)s
            AND toDate(timestamp) = toDate(parseDateTimeBestEffort(%(target_timestamp)s))
            AND event = '$ai_generation'
            AND uuid = %(event_id)s
        LIMIT 1
    """

    result = await database_sync_to_async(sync_execute, thread_sensitive=False)(
        query, {"event_id": inputs.target_event_id, "team_id": team_id, "target_timestamp": inputs.timestamp}
    )

    if not result:
        logger.exception("Event not found", target_event_id=inputs.target_event_id, team_id=team_id)
        raise ValueError(f"Event {inputs.target_event_id} not found for team {team_id}")

    row = result[0]
    event_data = {
        "uuid": str(row[0]),
        "event": row[1],
        "properties": json.loads(row[2]) if isinstance(row[2], str) else row[2],
        "timestamp": row[3],
        "team_id": row[4],
        "distinct_id": row[5],
        "person_id": str(row[6]) if row[6] is not None else None,
    }
    return event_data


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

    if evaluation["evaluation_type"] != "llm_judge" or evaluation["output_type"] != "boolean":
        raise ApplicationError(
            f"Unsupported evaluation: {evaluation['evaluation_type']}/{evaluation['output_type']}",
            non_retryable=True,
        )

    evaluation_config = evaluation.get("evaluation_config", {})
    prompt = evaluation_config.get("prompt")
    if not prompt:
        raise ApplicationError("Missing prompt in evaluation_config", non_retryable=True)

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
    if content is None:
        logger.exception("LLM judge returned empty response", evaluation_id=evaluation["id"])
        raise ValueError(f"LLM judge returned empty response for evaluation {evaluation['id']}")

    try:
        result = json.loads(content)
        verdict = bool(result.get("verdict", False))
        reasoning = result.get("reasoning", "No reasoning provided")
        return {"verdict": verdict, "reasoning": reasoning}
    except (json.JSONDecodeError, KeyError) as e:
        logger.exception(
            "Failed to parse LLM judge response", response=content, evaluation_id=evaluation["id"], error=str(e)
        )
        raise ValueError(f"Failed to parse LLM judge response for evaluation {evaluation['id']}: {str(e)}") from e


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
        evaluation = await temporalio.workflow.execute_activity(
            fetch_evaluation_activity,
            inputs,
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        event_data = await temporalio.workflow.execute_activity(
            fetch_target_event_activity,
            args=[inputs, evaluation["team_id"]],
            schedule_to_close_timeout=timedelta(seconds=30),
            # On ingestion, there's a race condition where the workflow can run
            # before the event is committed to ClickHouse. We should probably
            # find a more robust solution for this.
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=10),
                maximum_attempts=10,
                backoff_coefficient=2.0,
            ),
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
