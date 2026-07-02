"""Shared taxonomy for evaluation execution errors.

The split between user-actionable and PostHog-owned errors is load-bearing:
user errors disable the evaluation without failing the Temporal activity, while
PostHog-owned errors still raise so Temporal/Grafana stays useful.
"""

from dataclasses import dataclass
from typing import Literal

from temporalio.exceptions import ApplicationError

from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult

from products.ai_observability.backend.models.evaluations import EvaluationStatusReason
from products.ai_observability.backend.models.provider_keys import LLMProviderKey

EvaluationErrorOwner = Literal["user", "posthog"]
MAX_STATUS_REASON_DETAIL_LENGTH = 2000


@dataclass(frozen=True)
class EvaluationErrorSpec:
    error_type: str
    owner: EvaluationErrorOwner
    safe_message: str
    status_reason: str | None = None
    disables_evaluation: bool = False
    provider_key_state: str | None = None
    send_trial_usage_email: bool = False


USER_ERROR_SPECS: dict[str, EvaluationErrorSpec] = {
    "trial_limit_reached": EvaluationErrorSpec(
        error_type="trial_limit_reached",
        owner="user",
        safe_message="Trial evaluation limit reached. Add a provider API key to continue.",
        status_reason=EvaluationStatusReason.TRIAL_LIMIT_REACHED,
        disables_evaluation=True,
        send_trial_usage_email=True,
    ),
    "model_not_allowed": EvaluationErrorSpec(
        error_type="model_not_allowed",
        owner="user",
        safe_message="The selected model is not available on the trial plan.",
        status_reason=EvaluationStatusReason.MODEL_NOT_ALLOWED,
        disables_evaluation=True,
    ),
    "no_default_model": EvaluationErrorSpec(
        error_type="no_default_model",
        owner="user",
        safe_message="This provider has no default model. Set a model on the evaluation.",
        status_reason=EvaluationStatusReason.NO_DEFAULT_MODEL,
        disables_evaluation=True,
    ),
    "key_invalid": EvaluationErrorSpec(
        error_type="key_invalid",
        owner="user",
        safe_message="The provider API key is disabled. Re-validate or replace the key.",
        status_reason=EvaluationStatusReason.PROVIDER_KEY_INVALID,
        disables_evaluation=True,
    ),
    "key_not_found": EvaluationErrorSpec(
        error_type="key_not_found",
        owner="user",
        safe_message="The provider API key was deleted. Attach a provider API key before re-enabling.",
        status_reason=EvaluationStatusReason.PROVIDER_KEY_DELETED,
        disables_evaluation=True,
    ),
    "auth_error": EvaluationErrorSpec(
        error_type="auth_error",
        owner="user",
        safe_message="The provider API key is invalid or has been deleted.",
        status_reason=EvaluationStatusReason.PROVIDER_KEY_INVALID,
        disables_evaluation=True,
        provider_key_state=LLMProviderKey.State.INVALID,
    ),
    "permission_error": EvaluationErrorSpec(
        error_type="permission_error",
        owner="user",
        safe_message="The provider API key does not have access to this model.",
        status_reason=EvaluationStatusReason.PROVIDER_KEY_PERMISSION_DENIED,
        disables_evaluation=True,
        provider_key_state=LLMProviderKey.State.ERROR,
    ),
    "quota_error": EvaluationErrorSpec(
        error_type="quota_error",
        owner="user",
        safe_message="The provider API key has exceeded its quota.",
        status_reason=EvaluationStatusReason.PROVIDER_KEY_QUOTA_EXCEEDED,
        disables_evaluation=True,
        provider_key_state=LLMProviderKey.State.ERROR,
    ),
    "rate_limit": EvaluationErrorSpec(
        error_type="rate_limit",
        owner="user",
        safe_message="The provider API key is being rate limited.",
        status_reason=EvaluationStatusReason.PROVIDER_KEY_RATE_LIMITED,
        disables_evaluation=True,
        provider_key_state=LLMProviderKey.State.ERROR,
    ),
    "model_not_found": EvaluationErrorSpec(
        error_type="model_not_found",
        owner="user",
        safe_message="The selected model was not found. Choose an available model before re-enabling.",
        status_reason=EvaluationStatusReason.MODEL_NOT_FOUND,
        disables_evaluation=True,
    ),
    "hog_error": EvaluationErrorSpec(
        error_type="hog_error",
        owner="user",
        safe_message="The Hog evaluation code failed. Fix the code before re-enabling this evaluation.",
        status_reason=EvaluationStatusReason.HOG_ERROR,
        disables_evaluation=True,
    ),
}


POSTHOG_ERROR_SPECS: dict[str, EvaluationErrorSpec] = {
    "parse_error": EvaluationErrorSpec(
        error_type="parse_error",
        owner="posthog",
        safe_message="The judge response could not be parsed.",
    ),
    "provider_unavailable": EvaluationErrorSpec(
        error_type="provider_unavailable",
        owner="posthog",
        safe_message="The model provider request failed.",
    ),
    "emit_evaluation_event_failed": EvaluationErrorSpec(
        error_type="emit_evaluation_event_failed",
        owner="posthog",
        safe_message="The evaluation result event could not be emitted.",
    ),
}


EVALUATION_ERROR_SPECS: dict[str, EvaluationErrorSpec] = {
    **USER_ERROR_SPECS,
    **POSTHOG_ERROR_SPECS,
}


def get_evaluation_error_spec(error_type: str | None, *, is_byok: bool = False) -> EvaluationErrorSpec | None:
    if error_type == "model_not_found" and not is_byok:
        return None
    if error_type is None:
        return None
    return EVALUATION_ERROR_SPECS.get(error_type)


def require_user_error_spec(error_type: str, *, is_byok: bool = False) -> EvaluationErrorSpec:
    spec = get_evaluation_error_spec(error_type, is_byok=is_byok)
    if spec is None or spec.owner != "user":
        raise ValueError(f"Expected user-actionable evaluation error spec for {error_type}")
    return spec


def application_error_details(error: ApplicationError) -> dict[str, str | int | float | bool | None]:
    if not error.details:
        return {}
    details = error.details[0]
    if isinstance(details, dict):
        return details
    return {}


def terminal_user_error_result(
    *,
    spec: EvaluationErrorSpec,
    message: str | None,
    allows_na: bool,
    provider: str | None = None,
    model: str | None = None,
    key_id: str | None = None,
    is_byok: bool = False,
) -> EvaluationActivityResult:
    result: EvaluationActivityResult = {
        "result_type": "boolean",
        "verdict": None,
        "reasoning": spec.safe_message if not message else message,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "is_byok": is_byok,
        "key_id": key_id,
        "allows_na": allows_na,
        "skipped": True,
        "skip_reason": spec.error_type,
        "terminal_user_error": True,
        "status_reason": spec.status_reason,
    }
    if provider:
        result["provider"] = provider
    if model:
        result["model"] = model
    if spec.provider_key_state:
        result["provider_key_state"] = spec.provider_key_state
    if allows_na:
        result["applicable"] = False
    return result


def terminal_user_error_result_from_application_error(
    error: ApplicationError,
    *,
    allows_na: bool,
    provider: str | None = None,
    model: str | None = None,
    key_id: str | None = None,
    is_byok: bool = False,
) -> EvaluationActivityResult | None:
    details = application_error_details(error)
    error_type = details.get("error_type")
    detail_key_id = details.get("key_id")
    resolved_is_byok = is_byok or bool(detail_key_id)
    spec = get_evaluation_error_spec(str(error_type) if error_type else None, is_byok=resolved_is_byok)
    if spec is None or spec.owner != "user":
        return None

    detail_provider = details.get("provider")
    detail_model = details.get("model")
    return terminal_user_error_result(
        spec=spec,
        message=error.message,
        allows_na=allows_na,
        provider=str(detail_provider) if detail_provider else provider,
        model=str(detail_model) if detail_model else model,
        key_id=str(detail_key_id) if detail_key_id else key_id,
        is_byok=resolved_is_byok,
    )


def status_reason_detail_for_terminal_user_error(spec: EvaluationErrorSpec, message: str | None) -> str | None:
    if spec.error_type != "hog_error" or not message:
        return None

    if len(message) <= MAX_STATUS_REASON_DETAIL_LENGTH:
        return message
    return f"{message[: MAX_STATUS_REASON_DETAIL_LENGTH - 3]}..."


def is_terminal_user_error_result(result: EvaluationActivityResult) -> bool:
    return result.get("terminal_user_error") is True
