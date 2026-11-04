import structlog
from celery import shared_task

from posthog.temporal.ai_observability.evaluation_errors import require_user_error_spec
from posthog.temporal.ai_observability.model_resolution import active_key_fallback

from products.ai_observability.backend.llm.client import Client
from products.ai_observability.backend.llm.errors import ModelNotFoundError, ModelPermissionError, UnsupportedModelError
from products.ai_observability.backend.llm.types import CompletionRequest
from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.evaluations import Evaluation
from products.ai_observability.backend.models.provider_keys import LLMProviderKey

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, soft_time_limit=60, time_limit=90)
def check_evaluation_model(team_id: int, evaluation_id: str, provider: str, model: str) -> None:
    """Try a judge's new model with its key, so a model the key can't use errors the evaluation now, not on its first run."""
    evaluation = (
        Evaluation.objects.filter(team_id=team_id, id=evaluation_id).select_related("model_configuration").first()
    )
    if evaluation is None or evaluation.model_configuration is None:
        return
    provider_key = evaluation.model_configuration.provider_key
    if provider_key is None:
        config = EvaluationConfig.objects.filter(team_id=team_id).first()
        provider_key = active_key_fallback(config, provider) if config else None
    if provider_key is None or provider_key.state != LLMProviderKey.State.OK:
        return

    request = CompletionRequest(
        model=model, messages=[{"role": "user", "content": "Hi"}], provider=provider, max_tokens=16
    )
    try:
        Client(provider_key=provider_key, capture_analytics=False).complete(request)
        return
    except ModelNotFoundError:
        error_type = "model_not_found"
    except UnsupportedModelError:
        error_type = "model_not_supported"
    except ModelPermissionError:
        error_type = "permission_error"
    except Exception:
        # Any other failure, an outage included, says nothing about the model, so the evaluation keeps running.
        logger.info("evaluation_model_check_skipped", team_id=team_id, provider=provider, model=model, exc_info=True)
        return

    evaluation.refresh_from_db()
    current = evaluation.model_configuration
    # The model can change again while the call runs.
    if current is not None and (current.provider, current.model) == (provider, model):
        spec = require_user_error_spec(error_type, is_byok=True)
        evaluation.set_status("error", spec.status_reason, spec.safe_message)
