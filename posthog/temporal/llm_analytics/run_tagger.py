import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
import temporalio
from pydantic import BaseModel, Field
from structlog.contextvars import bind_contextvars
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.api.capture import capture_internal
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.message_utils import extract_text_from_messages
from posthog.temporal.llm_analytics.run_evaluation import extract_event_io

from products.llm_analytics.backend.llm import TRIAL_MODEL_IDS, Client, CompletionRequest
from products.llm_analytics.backend.llm.config import get_eval_config
from products.llm_analytics.backend.llm.errors import (
    AuthenticationError,
    ModelNotFoundError,
    ModelPermissionError,
    QuotaExceededError,
    RateLimitError,
    StructuredOutputParseError,
)
from products.llm_analytics.backend.models.evaluation_config import EvaluationConfig
from products.llm_analytics.backend.models.provider_keys import LLMProviderKey
from products.llm_analytics.backend.models.taggers import Tagger

logger = structlog.get_logger(__name__)

DEFAULT_TAGGER_MODEL = "gpt-5-mini"
# Trial-funded fallback when no model_configuration is set — must stay on the allowlist
# so a future default-model bump can't silently bypass the TRIAL_MODEL_IDS guard.
assert DEFAULT_TAGGER_MODEL in TRIAL_MODEL_IDS, (
    f"DEFAULT_TAGGER_MODEL ({DEFAULT_TAGGER_MODEL}) must be in TRIAL_MODEL_IDS"
)

LLM_TAGGER_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=10),
    maximum_interval=timedelta(seconds=60),
    backoff_coefficient=2.0,
)


class TagResult(BaseModel):
    """Structured output for tagger results."""

    tags: list[str]
    reasoning: str


def build_tag_result_schema(tag_names: list[str], min_tags: int = 0, max_tags: int | None = None) -> type[TagResult]:
    """Build a TagResult schema with valid tag names and constraints in the field description.

    This ensures the JSON schema sent to the LLM provider includes the allowed
    tag values and min/max constraints, improving structured output reliability.
    """
    tag_list = ", ".join(f'"{name}"' for name in tag_names)

    constraint_parts = [f"Valid values: [{tag_list}]"]
    if min_tags > 0:
        constraint_parts.append(f"Minimum {min_tags} tag(s)")
    if max_tags is not None:
        constraint_parts.append(f"Maximum {max_tags} tag(s)")
    if min_tags == 0:
        constraint_parts.append("Can be empty if no tags apply")

    description = "Tags to apply. " + ". ".join(constraint_parts) + "."

    class DynamicTagResult(TagResult):
        tags: list[str] = Field(description=description)
        reasoning: str = Field(description="Brief explanation for why these tags were selected")

    DynamicTagResult.__name__ = "TagResult"
    DynamicTagResult.__qualname__ = "TagResult"
    return DynamicTagResult


def build_tagger_system_prompt(prompt: str, tags: list[dict[str, str]], min_tags: int, max_tags: int | None) -> str:
    """Build the system prompt for the LLM tagger."""
    tag_lines = []
    for tag in tags:
        name = tag["name"]
        description = tag.get("description", "")
        if description:
            tag_lines.append(f"- {name}: {description}")
        else:
            tag_lines.append(f"- {name}")

    tag_list = "\n".join(tag_lines)

    constraint_parts = []
    if min_tags > 0:
        constraint_parts.append(f"at least {min_tags}")
    if max_tags is not None:
        constraint_parts.append(f"at most {max_tags}")

    if constraint_parts:
        constraint = f"Select {' and '.join(constraint_parts)} tags."
    else:
        constraint = "Select as many tags as apply."

    return f"""You are a tagger. Given the following AI generation, select which of these tags apply.

{prompt}

Available tags:
{tag_list}

{constraint} Only use tags from the list above. If no tags apply, return an empty list."""


@dataclass
class RunTaggerInputs:
    tagger_id: str
    event_data: dict[str, Any]

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "tagger_id": self.tagger_id,
            "team_id": self.event_data.get("team_id"),
        }


@temporalio.activity.defn
async def fetch_tagger_activity(inputs: RunTaggerInputs) -> dict[str, Any]:
    """Fetch tagger config from Postgres."""
    bind_contextvars(team_id=inputs.event_data.get("team_id"), tagger_id=inputs.tagger_id)

    def _fetch():
        try:
            # Only joins what's actually read below — provider_key is fetched separately
            # in execute_tagger_activity by id, so don't widen the join here.
            tagger = Tagger.objects.select_related("model_configuration").get(
                id=inputs.tagger_id, team_id=inputs.event_data["team_id"]
            )
        except Tagger.DoesNotExist:
            logger.exception("Tagger not found", tagger_id=inputs.tagger_id)
            raise ValueError(f"Tagger {inputs.tagger_id} not found")

        # Short-circuit when the tagger has been disabled (e.g. by a prior trial-limit
        # trip) before we run a lagging event through it. The workflow surfaces this
        # as a skipped result rather than an error.
        if not tagger.enabled:
            raise ApplicationError(
                f"Tagger {inputs.tagger_id} is disabled.",
                {"error_type": "tagger_disabled"},
                non_retryable=True,
            )

        model_configuration = None
        if tagger.model_configuration:
            mc = tagger.model_configuration
            model_configuration = {
                "provider": mc.provider,
                "model": mc.model,
                "provider_key_id": str(mc.provider_key_id) if mc.provider_key_id else None,
            }

        return {
            "id": str(tagger.id),
            "name": tagger.name,
            "tagger_type": tagger.tagger_type,
            "tagger_config": tagger.tagger_config,
            "team_id": tagger.team_id,
            "model_configuration": model_configuration,
        }

    return await database_sync_to_async(_fetch)()


@dataclass
class ExecuteTaggerInputs:
    tagger: dict[str, Any]
    event_data: dict[str, Any]

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.tagger.get("team_id"),
            "tagger_id": self.tagger.get("id"),
        }


@temporalio.activity.defn
async def execute_tagger_activity(inputs: ExecuteTaggerInputs) -> dict[str, Any]:
    """Execute LLM tagger to classify the target event."""
    from django.utils import timezone

    tagger = inputs.tagger
    event_data = inputs.event_data

    tagger_config = tagger.get("tagger_config", {})
    prompt = tagger_config.get("prompt")
    if not prompt:
        raise ApplicationError("Missing prompt in tagger_config", non_retryable=True)

    tags = tagger_config.get("tags", [])
    if not tags:
        raise ApplicationError("No tags defined in tagger_config", non_retryable=True)

    min_tags = tagger_config.get("min_tags", 0)
    max_tags = tagger_config.get("max_tags")

    # Resolve model configuration and API key
    team_id = tagger["team_id"]
    model_configuration = tagger.get("model_configuration")

    def _get_provider_key_by_id(key_id: str) -> LLMProviderKey:
        try:
            key = LLMProviderKey.objects.get(id=key_id, team_id=team_id)
            if key.state != LLMProviderKey.State.OK:
                raise ApplicationError(
                    f"Your API key is {key.state}. Please fix or replace it.",
                    {"error_type": "key_invalid", "key_id": str(key.id), "key_state": key.state},
                    non_retryable=True,
                )
            key.last_used_at = timezone.now()
            key.save(update_fields=["last_used_at"])
            return key
        except LLMProviderKey.DoesNotExist:
            raise ApplicationError(
                "Provider key not found.",
                {"error_type": "key_not_found", "key_id": key_id},
                non_retryable=True,
            )

    def _check_trial_quota() -> None:
        config, _ = EvaluationConfig.objects.get_or_create(team_id=team_id)
        if config.trial_evals_used >= config.trial_eval_limit:
            raise ApplicationError(
                f"Trial limit ({config.trial_eval_limit}) reached. Add your own API key to continue.",
                {"error_type": "trial_limit_reached", "trial_eval_limit": config.trial_eval_limit},
                non_retryable=True,
            )

    if model_configuration:
        provider = model_configuration["provider"]
        model = model_configuration["model"]
        provider_key_id = model_configuration.get("provider_key_id")

        if provider_key_id:
            provider_key = await database_sync_to_async(_get_provider_key_by_id)(provider_key_id)
        else:
            # Trial mode — enforce allowlist so teams can't run expensive non-trial
            # models on PostHog-funded credits. Matches the guard in execute_llm_judge_activity.
            if model not in TRIAL_MODEL_IDS:
                raise ApplicationError(
                    f"Model '{model}' is not available on the trial plan. Please add your own API key to use this model.",
                    {"error_type": "model_not_allowed", "model": model},
                    non_retryable=True,
                )
            await database_sync_to_async(_check_trial_quota)()
            provider_key = None
    else:
        provider = "openai"
        model = DEFAULT_TAGGER_MODEL
        await database_sync_to_async(_check_trial_quota)()
        provider_key = None

    is_byok = provider_key is not None
    key_id = str(provider_key.id) if provider_key else None

    # Build context from event
    event_type = event_data["event"]
    properties = event_data["properties"]
    if isinstance(properties, str):
        properties = json.loads(properties)

    input_raw, output_raw = extract_event_io(event_type, properties)
    input_data = extract_text_from_messages(input_raw)
    output_data = extract_text_from_messages(output_raw)

    system_prompt = build_tagger_system_prompt(prompt, tags, min_tags, max_tags)
    tag_names = [tag["name"] for tag in tags]
    response_format = build_tag_result_schema(tag_names, min_tags, max_tags)

    user_prompt = f"""Input: {input_data}

Output: {output_data}"""

    config = get_eval_config(provider) if provider_key is None else None

    client = Client(
        provider_key=provider_key,
        config=config,
        capture_analytics=False,
    )

    try:
        response = client.complete(
            CompletionRequest(
                model=model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                provider=provider,
                response_format=response_format,
            )
        )
    except AuthenticationError:
        if is_byok:
            raise ApplicationError(
                "API key is invalid or has been deleted.",
                {"error_type": "auth_error", "key_id": key_id, "provider": provider},
                non_retryable=True,
            )
        raise
    except ModelPermissionError:
        if is_byok:
            raise ApplicationError(
                "API key doesn't have access to this model.",
                {"error_type": "permission_error", "key_id": key_id, "provider": provider},
                non_retryable=True,
            )
        raise
    except QuotaExceededError:
        if is_byok:
            raise ApplicationError(
                "API key has exceeded its quota.",
                {"error_type": "quota_error", "key_id": key_id, "provider": provider},
                non_retryable=True,
            )
        raise
    except RateLimitError:
        if is_byok:
            raise ApplicationError(
                "API key is being rate limited.",
                {"error_type": "rate_limit", "key_id": key_id, "provider": provider},
                non_retryable=True,
            )
        raise
    except ModelNotFoundError:
        raise ApplicationError(
            f"Model '{model}' not found.",
            non_retryable=True,
        )
    except StructuredOutputParseError as e:
        raise ApplicationError(
            str(e),
            {"error_type": "parse_error"},
            non_retryable=True,
        ) from e

    result = response.parsed
    if result is None:
        logger.error("LLM tagger returned empty structured response", tagger_id=tagger["id"])
        raise ValueError(f"LLM tagger returned empty structured response for tagger {tagger['id']}")

    if not isinstance(result, TagResult):
        raise TypeError(f"Expected TagResult, got {type(result).__name__} for tagger {tagger['id']}")

    # Validate tags — strip any not in the configured set
    valid_tag_names = {tag["name"] for tag in tags}
    validated_tags = [t for t in result.tags if t in valid_tag_names]

    # Enforce min/max constraints
    if max_tags is not None:
        validated_tags = validated_tags[:max_tags]

    if min_tags > 0 and len(validated_tags) < min_tags:
        logger.warning(
            "Tagger returned fewer tags than min_tags",
            tagger_id=tagger["id"],
            min_tags=min_tags,
            actual_tags=len(validated_tags),
            tags=validated_tags,
        )

    usage = response.usage

    bind_contextvars(provider=provider, model=model)

    return {
        "tags": validated_tags,
        "reasoning": result.reasoning,
        "input_tokens": usage.input_tokens if usage else 0,
        "output_tokens": usage.output_tokens if usage else 0,
        "total_tokens": usage.total_tokens if usage else 0,
        "is_byok": is_byok,
        "key_id": key_id,
        "model": model,
        "provider": provider,
    }


def run_hog_tagger(bytecode: list, event_data: dict[str, Any], valid_tag_names: set[str]) -> dict[str, Any]:
    """Run compiled Hog bytecode to tag a single event.

    The Hog code should return a list of tag name strings.
    Returns {"tags": list[str], "reasoning": str, "error": str | None}.
    """
    from common.hogvm.python.execute import execute_bytecode
    from common.hogvm.python.utils import HogVMException, HogVMMemoryExceededException, HogVMRuntimeExceededException

    properties = event_data["properties"]
    if isinstance(properties, str):
        properties = json.loads(properties)

    event_type = event_data["event"]
    input_raw, output_raw = extract_event_io(event_type, properties)

    input_val = json.dumps(input_raw) if isinstance(input_raw, (list, dict)) else (input_raw or "")
    output_val = json.dumps(output_raw) if isinstance(output_raw, (list, dict)) else (output_raw or "")

    globals_dict: dict[str, Any] = {
        "input": input_val,
        "output": output_val,
        "properties": properties,
        "event": {
            "uuid": event_data.get("uuid", ""),
            "event": event_type,
            "distinct_id": event_data.get("distinct_id", ""),
        },
        "tags": sorted(valid_tag_names),
    }

    try:
        response = execute_bytecode(
            bytecode,
            globals=globals_dict,
            timeout=timedelta(seconds=5),
            team=None,
        )
    except HogVMRuntimeExceededException:
        return {"tags": [], "reasoning": "", "error": "Execution timed out (5s limit exceeded)"}
    except HogVMMemoryExceededException:
        return {"tags": [], "reasoning": "", "error": "Memory limit exceeded"}
    except HogVMException as e:
        return {"tags": [], "reasoning": "", "error": f"Runtime error: {e}"}
    except Exception:
        logger.exception("Unexpected error executing Hog tagger bytecode")
        return {"tags": [], "reasoning": "", "error": "Unexpected error during tagging"}

    reasoning = "\n".join(response.stdout) if response.stdout else ""

    # Expect a list of strings
    result = response.result
    if result is None:
        return {"tags": [], "reasoning": reasoning, "error": None}

    if isinstance(result, str):
        result = [result]

    if not isinstance(result, list):
        return {
            "tags": [],
            "reasoning": reasoning,
            "error": f"Must return a list of tag names, got {type(result).__name__}: {result}",
        }

    # Filter to valid tags only (skip filtering when no whitelist is defined — Hog code is user-controlled)
    if valid_tag_names:
        tags = [str(t) for t in result if str(t) in valid_tag_names]
    else:
        tags = [str(t) for t in result]

    return {"tags": tags, "reasoning": reasoning, "error": None}


@temporalio.activity.defn
async def execute_hog_tagger_activity(tagger: dict[str, Any], event_data: dict[str, Any]) -> dict[str, Any]:
    """Execute Hog code to tag the target event."""
    if tagger.get("tagger_type") != "hog":
        raise ApplicationError(
            f"Unsupported tagger type: {tagger.get('tagger_type')}",
            non_retryable=True,
        )

    tagger_config = tagger.get("tagger_config", {})
    bytecode = tagger_config.get("bytecode")
    if not bytecode:
        raise ApplicationError("Missing bytecode in tagger_config", non_retryable=True)

    tags_def = tagger_config.get("tags", [])
    valid_tag_names = {tag["name"] for tag in tags_def}

    def _execute():
        return run_hog_tagger(bytecode, event_data, valid_tag_names)

    result = await database_sync_to_async(_execute, thread_sensitive=False)()

    if result["error"]:
        raise ApplicationError(
            f"Hog tagger error: {result['error']}",
            non_retryable=True,
        )

    return {
        "tags": result["tags"],
        "reasoning": result["reasoning"],
        "is_hog": True,
    }


@dataclass
class EmitTaggerEventInputs:
    tagger: dict[str, Any]
    event_data: dict[str, Any]
    result: dict[str, Any]
    start_time: datetime

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.event_data.get("team_id"),
            "tagger_id": self.tagger.get("id"),
        }


@temporalio.activity.defn
async def emit_tagger_event_activity(inputs: EmitTaggerEventInputs) -> None:
    """Emit $ai_tag event via capture_internal."""
    tagger = inputs.tagger
    event_data = inputs.event_data
    result = inputs.result
    start_time = inputs.start_time

    def _emit():
        try:
            team = Team.objects.get(id=event_data["team_id"])
        except Team.DoesNotExist:
            logger.exception("Team not found", team_id=event_data["team_id"])
            raise ValueError(f"Team {event_data['team_id']} not found")

        properties_raw = (
            json.loads(event_data["properties"])
            if isinstance(event_data["properties"], str)
            else event_data["properties"]
        )

        properties: dict[str, Any] = {
            "$ai_tagger_id": tagger["id"],
            "$ai_tagger_name": tagger["name"],
            "$ai_tagger_type": "hog" if result.get("is_hog") else "llm",
            "$ai_tags": result["tags"],
            "$ai_tag_count": len(result["tags"]),
            "$ai_tag_reasoning": result["reasoning"],
            "$ai_tagger_start_time": start_time.isoformat(),
            "$ai_target_event_id": event_data["uuid"],
            "$ai_target_event_type": event_data["event"],
            "$ai_trace_id": properties_raw.get("$ai_trace_id"),
        }

        # LLM-only attribution — Hog taggers execute bytecode locally and have no
        # model/provider/key metadata, so omit these properties for Hog runs rather
        # than falsely tagging them as gpt-5-mini/openai/posthog-key.
        if not result.get("is_hog"):
            properties.update(
                {
                    "$ai_model": result.get("model", DEFAULT_TAGGER_MODEL),
                    "$ai_provider": result.get("provider", "openai"),
                    "$ai_input_tokens": result.get("input_tokens", 0),
                    "$ai_output_tokens": result.get("output_tokens", 0),
                    "$ai_tagger_key_type": "byok" if result.get("is_byok") else "posthog",
                    "$ai_tagger_key_id": result.get("key_id"),
                }
            )

        event_timestamp = datetime.now(UTC)

        resp = capture_internal(
            token=team.api_token,
            event_name="$ai_tag",
            event_source="llm_analytics_tagger",
            distinct_id=event_data["distinct_id"],
            timestamp=event_timestamp,
            properties=properties,
            process_person_profile=True,
        )
        resp.raise_for_status()

    await database_sync_to_async(_emit, thread_sensitive=False)()


@temporalio.activity.defn
async def disable_tagger_activity(tagger_id: str, team_id: int) -> None:
    """Disable a tagger when trial limit is reached.

    Uses ``.update()`` to bypass ``Tagger.save()``'s bytecode recompilation (matching
    ``disable_evaluation_activity``'s pattern), then publishes the reload-taggers
    notification manually — otherwise workers keep the disabled tagger in memory
    until something else triggers a reload.
    """
    from django.db import transaction

    from posthog.plugins.plugin_server_api import reload_taggers_on_workers

    def _disable():
        updated = Tagger.objects.filter(id=tagger_id, team_id=team_id).update(enabled=False)
        if updated:
            transaction.on_commit(lambda: reload_taggers_on_workers(team_id=team_id, tagger_ids=[tagger_id]))

    await database_sync_to_async(_disable)()


@temporalio.workflow.defn(name="run-tagger")
class RunTaggerWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunTaggerInputs:
        return RunTaggerInputs(
            tagger_id=inputs[0],
            event_data=json.loads(inputs[1]),
        )

    @temporalio.workflow.run
    async def run(self, inputs: RunTaggerInputs) -> dict[str, Any]:
        start_time = temporalio.workflow.now()

        # Activity 1: Fetch tagger config
        try:
            tagger = await temporalio.workflow.execute_activity(
                fetch_tagger_activity,
                inputs,
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except temporalio.exceptions.ActivityError as e:
            if isinstance(e.cause, ApplicationError) and e.cause.details:
                details = e.cause.details[0]
                if details.get("error_type") == "tagger_disabled":
                    return {
                        "tags": [],
                        "skipped": True,
                        "skip_reason": "tagger_disabled",
                        "message": e.cause.message,
                        "tagger_id": inputs.tagger_id,
                    }
            raise

        tagger_type = tagger.get("tagger_type", "llm")

        # Activity 2: Execute tagger based on type
        if tagger_type == "hog":
            # Hog taggers are deterministic — don't retry
            result = await temporalio.workflow.execute_activity(
                execute_hog_tagger_activity,
                args=[tagger, inputs.event_data],
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        else:
            # LLM tagger
            try:
                result = await temporalio.workflow.execute_activity(
                    execute_tagger_activity,
                    ExecuteTaggerInputs(tagger=tagger, event_data=inputs.event_data),
                    schedule_to_close_timeout=timedelta(minutes=6),
                    retry_policy=LLM_TAGGER_RETRY_POLICY,
                )
            except temporalio.exceptions.ActivityError as e:
                if isinstance(e.cause, ApplicationError) and e.cause.details:
                    details = e.cause.details[0]
                    error_type = details.get("error_type")

                    if error_type in ("trial_limit_reached", "key_invalid", "parse_error", "model_not_allowed"):
                        if error_type in ("trial_limit_reached", "model_not_allowed"):
                            await temporalio.workflow.execute_activity(
                                disable_tagger_activity,
                                args=[tagger["id"], tagger["team_id"]],
                                schedule_to_close_timeout=timedelta(seconds=30),
                                retry_policy=RetryPolicy(maximum_attempts=2),
                            )
                            if temporalio.workflow.patched("trial-usage-email"):
                                try:
                                    from posthog.temporal.llm_analytics.run_evaluation import (
                                        SendTrialUsageEmailInputs,
                                        send_trial_usage_email_activity,
                                    )

                                    await temporalio.workflow.execute_activity(
                                        send_trial_usage_email_activity,
                                        SendTrialUsageEmailInputs(team_id=tagger["team_id"], threshold_pct=100),
                                        activity_id=f"send-trial-usage-email-100pct-tagger-{tagger['team_id']}",
                                        schedule_to_close_timeout=timedelta(seconds=30),
                                        retry_policy=RetryPolicy(maximum_attempts=2),
                                    )
                                except Exception:
                                    temporalio.workflow.logger.exception(
                                        "Failed to send trial exhausted email",
                                        team_id=tagger["team_id"],
                                    )
                        return {
                            "tags": [],
                            "skipped": True,
                            "skip_reason": error_type,
                            "message": e.cause.message,
                            "tagger_id": tagger["id"],
                        }

                    # Update key state for API-related errors
                    from posthog.temporal.llm_analytics.run_evaluation import update_key_state_activity

                    key_id = details.get("key_id")
                    if key_id and error_type in ("auth_error", "permission_error", "quota_error", "rate_limit"):
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

        # Increment trial counter if using PostHog key (LLM taggers only — Hog taggers have no LLM cost)
        if tagger_type != "hog" and not result.get("is_byok"):
            from posthog.temporal.llm_analytics.run_evaluation import (
                SendTrialUsageEmailInputs,
                increment_trial_eval_count_activity,
                send_trial_usage_email_activity,
            )

            threshold_pct = await temporalio.workflow.execute_activity(
                increment_trial_eval_count_activity,
                tagger["team_id"],
                activity_id=f"increment-trial-tagger-{tagger['id']}",
                schedule_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            if threshold_pct is not None and temporalio.workflow.patched("trial-usage-email"):
                try:
                    await temporalio.workflow.execute_activity(
                        send_trial_usage_email_activity,
                        SendTrialUsageEmailInputs(team_id=tagger["team_id"], threshold_pct=threshold_pct),
                        activity_id=f"send-trial-usage-email-{threshold_pct}pct-tagger-{tagger['team_id']}",
                        schedule_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                except Exception:
                    temporalio.workflow.logger.exception(
                        "Failed to send trial usage email",
                        team_id=tagger["team_id"],
                        threshold_pct=threshold_pct,
                    )

        # Activity 3: Emit tagger event
        await temporalio.workflow.execute_activity(
            emit_tagger_event_activity,
            EmitTaggerEventInputs(
                tagger=tagger,
                event_data=inputs.event_data,
                result=result,
                start_time=start_time,
            ),
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        return {
            "tags": result["tags"],
            "reasoning": result["reasoning"],
            "tagger_id": tagger["id"],
        }
