import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings

import structlog
import temporalio
from pydantic import BaseModel, model_validator
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.models.event.util import create_event
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.message_utils import extract_text_from_messages

from products.llm_analytics.backend.models.evaluation_config import EvaluationConfig
from products.llm_analytics.backend.models.evaluations import Evaluation
from products.llm_analytics.backend.models.provider_keys import LLMProviderKey

logger = structlog.get_logger(__name__)

# Default model for LLM judge
DEFAULT_JUDGE_MODEL = "gpt-5-mini"


class BooleanEvalResult(BaseModel):
    """Structured output for boolean evaluation results"""

    reasoning: str
    verdict: bool


class BooleanWithNAEvalResult(BaseModel):
    """Structured output for boolean with N/A evaluation results.

    When the evaluation criteria doesn't apply to the input/output,
    applicable should be False and verdict should be None.
    """

    reasoning: str
    applicable: bool
    verdict: bool | None = None

    @model_validator(mode="after")
    def validate_verdict_consistency(self) -> "BooleanWithNAEvalResult":
        if self.applicable and self.verdict is None:
            raise ValueError("verdict is required when applicable is true")
        if not self.applicable and self.verdict is not None:
            raise ValueError("verdict must be null when applicable is false")
        return self


@dataclass
class OutputTypeConfig:
    """Configuration for each evaluation output type"""

    response_format: type[BooleanEvalResult] | type[BooleanWithNAEvalResult]
    instructions: str


OUTPUT_TYPE_CONFIGS: dict[str, OutputTypeConfig] = {
    "boolean": OutputTypeConfig(
        response_format=BooleanEvalResult,
        instructions="Provide a brief reasoning (1 sentence) and a boolean verdict (true/false).",
    ),
    "boolean_with_na": OutputTypeConfig(
        response_format=BooleanWithNAEvalResult,
        instructions="""First, determine if this evaluation criteria is applicable to the given input/output. If the criteria doesn't apply to this case mark it as not applicable.

Note: If the criteria above instructs you to return "N/A", "not applicable", or similar, treat that as applicable=false with verdict=null.

Return:
- applicable: true if the criteria applies to this input/output, false if it doesn't apply
- verdict: true if it passes, false if it fails, or null if not applicable
- reasoning: a brief explanation (1 sentence)""",
    ),
}


def build_system_prompt(prompt: str, output_type: str) -> str:
    """Build the system prompt for the LLM judge."""
    config = OUTPUT_TYPE_CONFIGS.get(output_type, OUTPUT_TYPE_CONFIGS["boolean"])
    return f"""You are an evaluator. Evaluate the following generation according to this criteria:

{prompt}

{config.instructions}"""


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
async def update_key_state_activity(key_id: str, state: str, error_message: str | None) -> None:
    """Update the state of an LLM provider key"""

    def _update():
        try:
            key = LLMProviderKey.objects.get(id=key_id)
            key.state = state
            key.error_message = error_message
            key.save(update_fields=["state", "error_message"])
        except LLMProviderKey.DoesNotExist:
            logger.warning("Tried to update state for non-existent key", key_id=key_id)

    await database_sync_to_async(_update)()


@temporalio.activity.defn
async def increment_trial_eval_count_activity(team_id: int) -> None:
    """Increment trial eval counter after successful execution with PostHog key"""
    from django.db.models import F

    def _increment():
        EvaluationConfig.objects.filter(team_id=team_id).update(trial_evals_used=F("trial_evals_used") + 1)

    await database_sync_to_async(_increment)()


@temporalio.activity.defn
async def execute_llm_judge_activity(evaluation: dict[str, Any], event_data: dict[str, Any]) -> dict[str, Any]:
    """Execute LLM judge to evaluate the target event.

    Fetches API key configuration internally to avoid passing sensitive data between activities.
    """
    from django.utils import timezone

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
    if output_type not in ("boolean", "boolean_with_na"):
        raise ApplicationError(
            f"Unsupported output type: {output_type}. Supported types: 'boolean', 'boolean_with_na'.",
            non_retryable=True,
        )

    # Fetch API key configuration (BYOK or trial)
    team_id = evaluation["team_id"]

    def _get_llm_config():
        config, _ = EvaluationConfig.objects.get_or_create(team_id=team_id)

        # Check if team has active BYOK key
        if config.active_provider_key:
            key = config.active_provider_key
            if key.state == LLMProviderKey.State.OK:
                key.last_used_at = timezone.now()
                key.save(update_fields=["last_used_at"])
                return {
                    "api_key": key.encrypted_config.get("api_key"),
                    "key_id": str(key.id),
                    "is_byok": True,
                }
            else:
                # Active key exists but is invalid - fail, don't fall back to trial
                return {
                    "error": "key_invalid",
                    "message": f"Your API key is {key.state}. Please fix or replace it.",
                    "key_id": str(key.id),
                    "key_state": key.state,
                }

        # No active key - check trial quota
        if config.trial_evals_used >= config.trial_eval_limit:
            return {
                "error": "trial_limit_reached",
                "message": f"Trial evaluation limit ({config.trial_eval_limit}) reached. "
                f"Add your own OpenAI API key to continue.",
            }

        return {
            "api_key": None,  # Will use settings.OPENAI_API_KEY
            "is_byok": False,
        }

    llm_config = await database_sync_to_async(_get_llm_config)()

    # Check for config errors
    if llm_config.get("error") == "trial_limit_reached":
        raise ApplicationError(
            llm_config["message"],
            {"error_type": "trial_limit_reached"},
            non_retryable=True,
        )

    if llm_config.get("error") == "key_invalid":
        raise ApplicationError(
            llm_config["message"],
            {
                "error_type": "key_invalid",
                "key_id": llm_config.get("key_id"),
                "key_state": llm_config.get("key_state"),
            },
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

    # Build judge prompt based on output type
    output_config = OUTPUT_TYPE_CONFIGS.get(output_type, OUTPUT_TYPE_CONFIGS["boolean"])
    system_prompt = build_system_prompt(prompt, output_type)
    response_format = output_config.response_format

    user_prompt = f"""Input: {input_data}

Output: {output_data}"""

    # Determine which API key to use
    if llm_config.get("api_key"):
        api_key = llm_config["api_key"]
        is_byok = True
        key_id = llm_config.get("key_id")
    else:
        api_key = settings.OPENAI_API_KEY
        is_byok = False
        key_id = None

    # Call OpenAI
    client = openai.OpenAI(api_key=api_key)

    try:
        response = client.beta.chat.completions.parse(
            model=DEFAULT_JUDGE_MODEL,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            response_format=response_format,
        )
    except openai.AuthenticationError:
        if is_byok:
            raise ApplicationError(
                "API key is invalid or has been deleted.",
                {"error_type": "auth_error", "key_id": key_id},
                non_retryable=True,
            )
        raise
    except openai.PermissionDeniedError:
        if is_byok:
            raise ApplicationError(
                "API key doesn't have access to this model.",
                {"error_type": "permission_error", "key_id": key_id},
                non_retryable=True,
            )
        raise
    except openai.RateLimitError as e:
        # Check if this is quota exceeded vs rate limit
        error_body = getattr(e, "body", {}) or {}
        error_code = error_body.get("error", {}).get("code", "")

        if error_code == "insufficient_quota":
            if is_byok:
                raise ApplicationError(
                    "API key has exceeded its quota.",
                    {"error_type": "quota_error", "key_id": key_id},
                    non_retryable=True,
                )
            raise
        # Regular rate limit - let it retry (default behavior)
        raise
    except openai.NotFoundError:
        raise ApplicationError(
            f"Model '{DEFAULT_JUDGE_MODEL}' not found.",
            non_retryable=True,
        )

    # Parse structured output
    result = response.choices[0].message.parsed
    if result is None:
        logger.exception("LLM judge returned empty structured response", evaluation_id=evaluation["id"])
        raise ValueError(f"LLM judge returned empty structured response for evaluation {evaluation['id']}")

    # Extract token usage from response
    usage = response.usage

    # Build result dict based on output type
    if output_type == "boolean_with_na" and isinstance(result, BooleanWithNAEvalResult):
        result_dict: dict[str, Any] = {
            "verdict": result.verdict,
            "reasoning": result.reasoning,
            "applicable": result.applicable,
            "input_tokens": usage.prompt_tokens if usage else 0,
            "output_tokens": usage.completion_tokens if usage else 0,
            "total_tokens": usage.total_tokens if usage else 0,
            "is_byok": is_byok,
            "key_id": key_id,
            "output_type": output_type,
        }
    elif isinstance(result, BooleanEvalResult):
        result_dict = {
            "verdict": result.verdict,
            "reasoning": result.reasoning,
            "input_tokens": usage.prompt_tokens if usage else 0,
            "output_tokens": usage.completion_tokens if usage else 0,
            "total_tokens": usage.total_tokens if usage else 0,
            "is_byok": is_byok,
            "key_id": key_id,
            "output_type": output_type,
        }
    else:
        raise ValueError(f"Unexpected result type: {type(result)}")

    return result_dict


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
        output_type = result.get("output_type", "boolean")

        properties: dict[str, Any] = {
            "$ai_evaluation_id": evaluation["id"],
            "$ai_evaluation_name": evaluation["name"],
            "$ai_evaluation_model": DEFAULT_JUDGE_MODEL,
            "$ai_evaluation_start_time": start_time.isoformat(),
            "$ai_evaluation_output_type": output_type,
            "$ai_evaluation_reasoning": result["reasoning"],
            "$ai_target_event_id": event_data["uuid"],
            "$ai_target_event_type": event_data["event"],
            "$ai_trace_id": event_data["properties"].get("$ai_trace_id"),
            "$ai_evaluation_key_type": "byok" if result.get("is_byok") else "posthog",
            "$ai_evaluation_key_id": result.get("key_id"),
        }

        # Handle result based on output type
        if output_type == "boolean_with_na":
            applicable = result.get("applicable", True)
            properties["$ai_evaluation_applicable"] = applicable
            # Only set result when applicable
            if applicable:
                properties["$ai_evaluation_result"] = result["verdict"]
        else:
            # Standard boolean output - always set result
            properties["$ai_evaluation_result"] = result["verdict"]

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

        # Activity 2: Execute LLM judge (fetches API key internally)
        try:
            result = await temporalio.workflow.execute_activity(
                execute_llm_judge_activity,
                args=[evaluation, event_data],
                schedule_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except temporalio.exceptions.ActivityError as e:
            if isinstance(e.cause, ApplicationError) and e.cause.details:
                details = e.cause.details[0]
                key_id = details.get("key_id")
                error_type = details.get("error_type")

                # Only update key state for errors related to the key itself
                if key_id and error_type in ("auth_error", "permission_error", "quota_error"):
                    new_state = (
                        LLMProviderKey.State.INVALID if error_type == "auth_error" else LLMProviderKey.State.ERROR
                    )
                    await temporalio.workflow.execute_activity(
                        update_key_state_activity,
                        args=[key_id, new_state, e.cause.message],
                        schedule_to_close_timeout=timedelta(seconds=10),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
            raise

        # Activity 3: Increment trial eval counter if using PostHog key
        if not result.get("is_byok"):
            await temporalio.workflow.execute_activity(
                increment_trial_eval_count_activity,
                evaluation["team_id"],
                activity_id=f"increment-trial-{evaluation['id']}",
                schedule_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

        # Activity 4: Emit evaluation event
        await temporalio.workflow.execute_activity(
            emit_evaluation_event_activity,
            args=[evaluation, event_data, result, start_time],
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # Activity 5: Emit internal telemetry (fire-and-forget)
        await temporalio.workflow.execute_activity(
            emit_internal_telemetry_activity,
            args=[evaluation, event_data["team_id"], result],
            schedule_to_close_timeout=timedelta(seconds=30),
        )

        return {
            "verdict": result["verdict"],
            "reasoning": result["reasoning"],
            "evaluation_id": evaluation["id"],
            "is_byok": result.get("is_byok", False),
        }
