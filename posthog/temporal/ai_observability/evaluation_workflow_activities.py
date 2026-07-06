import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.db import models, transaction

import structlog
import temporalio
from structlog.contextvars import bind_contextvars

from posthog.api.capture import capture_internal
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.ai_observability.evaluation_llm_judge import DEFAULT_JUDGE_MODEL
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult
from posthog.temporal.ai_observability.metrics import increment_emit_event_outcome

from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.evaluations import Evaluation, EvaluationStatus
from products.ai_observability.backend.models.provider_keys import LLMProviderKey

logger = structlog.get_logger(__name__)

SOURCE_AI_PROPERTIES_TO_COPY = ("$ai_prompt_name", "$ai_prompt_version")
TRIAL_NOTIFICATION_THRESHOLDS = [50, 75, 100]


@dataclass
class RunEvaluationInputs:
    evaluation_id: str
    event_data: dict[str, Any]

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "team_id": self.event_data.get("team_id"),
        }


@temporalio.activity.defn
async def fetch_evaluation_activity(inputs: RunEvaluationInputs) -> dict[str, Any]:
    """Fetch evaluation config from Postgres."""
    bind_contextvars(team_id=inputs.event_data.get("team_id"), evaluation_id=inputs.evaluation_id)

    def _fetch() -> dict[str, Any]:
        try:
            evaluation = Evaluation.objects.select_related(
                "model_configuration",
                "model_configuration__provider_key",
            ).get(id=inputs.evaluation_id, team_id=inputs.event_data["team_id"])

            model_configuration = None
            if evaluation.model_configuration:
                mc = evaluation.model_configuration
                model_configuration = {
                    "provider": mc.provider,
                    "model": mc.model,
                    "provider_key_id": str(mc.provider_key_id) if mc.provider_key_id else None,
                }

            return {
                "id": str(evaluation.id),
                "name": evaluation.name,
                "evaluation_type": evaluation.evaluation_type,
                "evaluation_config": evaluation.evaluation_config,
                "output_type": evaluation.output_type,
                "output_config": evaluation.output_config,
                "team_id": evaluation.team_id,
                "model_configuration": model_configuration,
                "enabled": evaluation.enabled,
                "deleted": evaluation.deleted,
            }
        except Evaluation.DoesNotExist:
            logger.exception("Evaluation not found", evaluation_id=inputs.evaluation_id)
            raise ValueError(f"Evaluation {inputs.evaluation_id} not found")

    return await database_sync_to_async(_fetch)()


@temporalio.activity.defn
async def update_key_state_activity(key_id: str, state: str, error_message: str | None) -> None:
    """Update the state of an LLM provider key."""

    def _update() -> None:
        try:
            key = LLMProviderKey.objects.get(id=key_id)
            key.state = state
            key.error_message = error_message
            key.save(update_fields=["state", "error_message"])
        except LLMProviderKey.DoesNotExist:
            logger.warning("Tried to update state for non-existent key", key_id=key_id)

    await database_sync_to_async(_update)()


@temporalio.activity.defn
async def increment_trial_eval_count_activity(team_id: int) -> int | None:
    """Increment trial eval counter after successful execution with PostHog key."""
    from django.db import connection

    def _increment() -> int | None:
        table = EvaluationConfig._meta.db_table
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {table}
                SET trial_evals_used = trial_evals_used + 1
                WHERE team_id = %s
                RETURNING trial_evals_used, trial_eval_limit
                """,
                [team_id],
            )
            row = cursor.fetchone()
            if row is None:
                logger.warning("No EvaluationConfig found for team during trial increment", team_id=team_id)
                return None
            trial_evals_used, trial_eval_limit = row

        for pct in TRIAL_NOTIFICATION_THRESHOLDS:
            if trial_evals_used == round(trial_eval_limit * pct / 100):
                return pct
        return None

    return await database_sync_to_async(_increment)()


@temporalio.activity.defn
async def disable_evaluation_activity(
    evaluation_id: str, team_id: int, status_reason: str = "", status_reason_detail: str | None = None
) -> bool:
    """Transition an evaluation into the ERROR state when the workflow hits a terminal skippable error.

    Returns True only for the first workflow that disables the evaluation. Later in-flight
    workflows can hit the same terminal error after the first transition, but shouldn't send
    duplicate disabled notifications or write duplicate activity log rows.
    """

    def _disable() -> bool:
        reason = status_reason or "trial_limit_reached"
        with transaction.atomic():
            evaluation = Evaluation.objects.select_for_update().filter(id=evaluation_id, team_id=team_id).first()
            if evaluation is None:
                return False

            if evaluation.status == EvaluationStatus.ERROR and not evaluation.enabled:
                return False

            evaluation.set_status("error", reason, status_reason_detail)
            return True

    return await database_sync_to_async(_disable)()


@dataclass
class SendTrialUsageEmailInputs:
    team_id: int
    threshold_pct: int


@temporalio.activity.defn
async def send_trial_usage_email_activity(inputs: SendTrialUsageEmailInputs) -> None:
    """Send an email to org members about trial evaluation usage."""

    def _send() -> None:
        from posthog.email import EmailMessage, is_email_available

        if not is_email_available(with_absolute_urls=True):
            logger.info(
                "Email not available, skipping trial usage notification",
                team_id=inputs.team_id,
                threshold_pct=inputs.threshold_pct,
            )
            return

        try:
            team = Team.objects.select_related("organization").get(id=inputs.team_id)
        except Team.DoesNotExist:
            logger.warning("Team not found for trial usage email", team_id=inputs.team_id)
            return

        config = EvaluationConfig.objects.filter(team_id=inputs.team_id).first()
        if not config:
            return

        max_listed = 20
        affected_qs = Evaluation.objects.filter(
            team_id=inputs.team_id,
            enabled=True,
            deleted=False,
        ).filter(models.Q(model_configuration__isnull=True) | models.Q(model_configuration__provider_key__isnull=True))
        total_affected = affected_qs.count()
        affected_evals = list(affected_qs.values_list("name", flat=True)[:max_listed])
        affected_evals_overflow = max(0, total_affected - max_listed)

        settings_url = f"/project/{team.pk}/settings/project-ai-observability#ai-observability-byok"
        campaign_key = f"llm_analytics_trial_{inputs.threshold_pct}pct_{team.id}"
        is_exhausted = inputs.threshold_pct >= 100

        if is_exhausted:
            subject = "Your AI observability trial evaluations have been used up"
            template_name = "ai_observability_trial_exhausted"
        else:
            subject = f"You've used {inputs.threshold_pct}% of your AI observability trial evaluations"
            template_name = "ai_observability_trial_warning"

        message = EmailMessage(
            campaign_key=campaign_key,
            subject=subject,
            template_name=template_name,
            template_context={
                "trial_eval_limit": config.trial_eval_limit,
                "trial_evals_used": config.trial_evals_used,
                "trial_evals_remaining": config.trial_evals_remaining,
                "threshold_pct": inputs.threshold_pct,
                "settings_url": settings_url,
                "affected_evals": affected_evals,
                "affected_evals_overflow": affected_evals_overflow,
            },
        )

        for user in team.organization.members.all():
            message.add_user_recipient(user)

        if message.to:
            message.send()
            logger.info(
                "Sent trial usage email",
                team_id=inputs.team_id,
                org_id=str(team.organization_id),
                threshold_pct=inputs.threshold_pct,
                recipient_count=len(message.to),
            )

    await database_sync_to_async(_send)()


@dataclass
class SendEvaluationDisabledEmailInputs:
    team_id: int
    evaluation_id: str
    evaluation_name: str
    status_reason: str
    human_readable_reason: str
    disabled_at: datetime | None = None


_STATUS_REASON_SUBJECTS = {
    "model_not_allowed": "Your AI observability evaluation was disabled because its model isn't supported on the trial plan",
    "no_default_model": "Your AI observability evaluation was disabled because no default model is configured",
    "provider_key_deleted": "Your AI observability evaluation was disabled because its provider API key was removed",
    "provider_key_invalid": "Your AI observability evaluation was disabled because its provider API key is invalid",
    "provider_key_permission_denied": "Your AI observability evaluation was disabled because its provider API key lacks model access",
    "provider_key_quota_exceeded": "Your AI observability evaluation was disabled because its provider API key quota was exceeded",
    "provider_key_rate_limited": "Your AI observability evaluation was disabled because its provider API key is being rate limited",
    "model_not_found": "Your AI observability evaluation was disabled because its model was not found",
    "hog_error": "Your AI observability evaluation was disabled because its Hog code failed",
}


@temporalio.activity.defn
async def send_evaluation_disabled_email_activity(inputs: SendEvaluationDisabledEmailInputs) -> None:
    """Email org members when an evaluation enters the ERROR state for a reason other than trial exhaustion."""

    def _send() -> None:
        from posthog.email import EmailMessage, is_email_available

        if not is_email_available(with_absolute_urls=True):
            logger.info(
                "Email not available, skipping evaluation disabled notification",
                team_id=inputs.team_id,
                evaluation_id=inputs.evaluation_id,
            )
            return

        try:
            team = Team.objects.select_related("organization").get(id=inputs.team_id)
        except Team.DoesNotExist:
            logger.warning("Team not found for evaluation disabled email", team_id=inputs.team_id)
            return

        settings_url = f"/project/{team.pk}/settings/project-ai-observability#ai-observability-byok"
        evaluation_url = f"/project/{team.pk}/ai-evals/evaluations/{inputs.evaluation_id}"
        campaign_key = f"llm_analytics_eval_disabled_{inputs.evaluation_id}_{inputs.status_reason}"
        if inputs.disabled_at is not None:
            campaign_key = f"{campaign_key}_{int(inputs.disabled_at.timestamp() * 1_000_000)}"
        subject = _STATUS_REASON_SUBJECTS.get(
            inputs.status_reason, f'Your evaluation "{inputs.evaluation_name}" has been disabled'
        )

        message = EmailMessage(
            campaign_key=campaign_key,
            subject=subject,
            template_name="ai_observability_evaluation_disabled",
            template_context={
                "evaluation_name": inputs.evaluation_name,
                "disabled_reason": inputs.human_readable_reason,
                "settings_url": settings_url,
                "evaluation_url": evaluation_url,
            },
        )

        for user in team.organization.members.all():
            message.add_user_recipient(user)

        if message.to:
            message.send()
            logger.info(
                "Sent evaluation disabled email",
                team_id=inputs.team_id,
                evaluation_id=inputs.evaluation_id,
                status_reason=inputs.status_reason,
                recipient_count=len(message.to),
            )

    await database_sync_to_async(_send)()


@dataclass
class EmitEvaluationEventInputs:
    evaluation: dict[str, Any]
    event_data: dict[str, Any]
    result: EvaluationActivityResult
    start_time: datetime

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.event_data.get("team_id"),
            "evaluation_id": self.evaluation.get("id"),
        }


def build_evaluation_event_properties(
    evaluation: dict[str, Any], result: EvaluationActivityResult, start_time: datetime
) -> dict[str, Any]:
    """Assemble the target-independent `$ai_evaluation` properties shared by all emit paths.

    Callers add the target linkage on top ($ai_target_id / $ai_target_type and friends) —
    generation evals point at the source event UUID, trace evals at the trace id.
    """
    allows_na = result.get("allows_na", False)
    evaluation_type = evaluation.get("evaluation_type", "llm_judge")

    properties: dict[str, Any] = {
        "$ai_evaluation_id": evaluation["id"],
        "$ai_evaluation_name": evaluation["name"],
        "$ai_evaluation_type": "online",
        "$ai_evaluation_runtime": evaluation_type,
        "$ai_evaluation_result_type": result["result_type"],
        "$ai_evaluation_start_time": start_time.isoformat(),
        "$ai_evaluation_reasoning": result["reasoning"],
    }

    if result.get("skipped"):
        properties["$ai_evaluation_skipped"] = True
        properties["$ai_evaluation_skip_reason"] = result.get("skip_reason")

    if evaluation_type == "llm_judge" and not result.get("skipped"):
        properties["$ai_model"] = result.get("model", DEFAULT_JUDGE_MODEL)
        properties["$ai_provider"] = result.get("provider", "openai")
        properties["$ai_input_tokens"] = result.get("input_tokens", 0)
        properties["$ai_output_tokens"] = result.get("output_tokens", 0)
        properties["$ai_evaluation_model"] = result.get("model", DEFAULT_JUDGE_MODEL)
        properties["$ai_evaluation_provider"] = result.get("provider", "openai")
        properties["$ai_evaluation_key_type"] = "byok" if result.get("is_byok") else "posthog"
        properties["$ai_evaluation_key_id"] = result.get("key_id")

    if result["result_type"] == "sentiment":
        properties["$ai_sentiment_label"] = result.get("sentiment_label")
        properties["$ai_sentiment_score"] = result.get("sentiment_score")
        properties["$ai_sentiment_scores"] = result.get("sentiment_scores")
        properties["$ai_sentiment_messages"] = result.get("sentiment_messages")
        properties["$ai_sentiment_message_count"] = result.get("sentiment_message_count")
    else:
        properties["$ai_evaluation_allows_na"] = allows_na
        if allows_na:
            applicable = result.get("applicable", True)
            properties["$ai_evaluation_applicable"] = applicable
            if applicable:
                properties["$ai_evaluation_result"] = result["verdict"]
        else:
            properties["$ai_evaluation_result"] = result["verdict"]

    return properties


@temporalio.activity.defn
async def emit_evaluation_event_activity(inputs: EmitEvaluationEventInputs) -> None:
    """Emit $ai_evaluation event via capture_internal so it routes through the ingestion pipeline for cost calculation."""
    evaluation = inputs.evaluation
    event_data = inputs.event_data
    result = inputs.result
    start_time = inputs.start_time

    def _emit() -> None:
        try:
            team = Team.objects.get(id=event_data["team_id"])
        except Team.DoesNotExist:
            logger.exception("Team not found", team_id=event_data["team_id"])
            raise ValueError(f"Team {event_data['team_id']} not found")

        source_props = (
            json.loads(event_data["properties"])
            if isinstance(event_data["properties"], str)
            else event_data["properties"]
        )

        properties = build_evaluation_event_properties(evaluation, result, start_time)
        properties.update(
            {
                "$ai_target_event_id": event_data["uuid"],
                "$ai_target_event_type": event_data["event"],
                "$ai_target_id": event_data["uuid"],
                "$ai_target_type": "generation_uuid",
                "$ai_trace_id": source_props.get("$ai_trace_id"),
                "$session_id": source_props.get("$session_id"),
            }
        )

        for property_name in SOURCE_AI_PROPERTIES_TO_COPY:
            if source_props.get(property_name) is not None:
                properties[property_name] = source_props[property_name]

        event_timestamp = datetime.now(UTC)

        capture_result = capture_internal(
            token=team.api_token,
            event_name="$ai_evaluation",
            event_source="llm_analytics_evaluation",
            distinct_id=event_data["distinct_id"],
            timestamp=event_timestamp,
            properties=properties,
            process_person_profile=True,
        )
        capture_result.raise_for_status()

    try:
        await database_sync_to_async(_emit, thread_sensitive=False)()
        increment_emit_event_outcome("success")
    except Exception:
        increment_emit_event_outcome("failed")
        raise


@dataclass
class EmitInternalTelemetryInputs:
    evaluation: dict[str, Any]
    team_id: int
    result: EvaluationActivityResult

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "evaluation_id": self.evaluation.get("id"),
        }


@temporalio.activity.defn
async def emit_internal_telemetry_activity(inputs: EmitInternalTelemetryInputs) -> None:
    """Emit telemetry event to PostHog org for internal tracking."""
    from posthog.tasks.usage_report import get_ph_client

    evaluation = inputs.evaluation
    team_id = inputs.team_id
    result = inputs.result

    def _emit_telemetry() -> None:
        team = Team.objects.get(id=team_id)
        organization_id = str(team.organization_id)

        ph_client = get_ph_client(sync_mode=True)
        ph_client.capture(
            distinct_id=f"org-{organization_id}",
            event="llm analytics evaluation executed",
            properties={
                "evaluation_id": evaluation["id"],
                "team_id": team_id,
                "model": result.get("model", DEFAULT_JUDGE_MODEL),
                "provider": result.get("provider", "openai"),
                "input_tokens": result.get("input_tokens", 0),
                "output_tokens": result.get("output_tokens", 0),
                "total_tokens": result.get("total_tokens", 0),
                "verdict": result["verdict"],
            },
            groups={"organization": organization_id, "instance": settings.SITE_URL},
        )
        ph_client.flush()

    await database_sync_to_async(_emit_telemetry, thread_sensitive=False)()
