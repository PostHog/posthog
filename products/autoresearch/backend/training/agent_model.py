"""Which model and reasoning effort a pipeline's training agent runs on.

Autoresearch sets its own default rather than inheriting the Tasks one: training runs as an
internal task, which skips team and user run preferences, so a change to the Tasks default
would otherwise change the training model and its cost without anyone choosing it.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError

from posthog.dataclasses import frozen

from products.autoresearch.backend.models import AutoresearchPipeline
from products.tasks.backend.facade.ai_run_defaults import validate_ai_run_preferences
from products.tasks.backend.facade.model_catalogue import ModelChoice, filter_unsupported_effort, offered_model_choices
from products.tasks.backend.facade.run_config import get_required_model_flag, get_runtime_adapter_for_model

AUTORESEARCH_DEFAULT_MODEL = "claude-opus-5-5"
AUTORESEARCH_DEFAULT_REASONING_EFFORT = "medium"


class AgentModelError(ValueError):
    pass


@frozen
class AgentRunConfig:
    runtime_adapter: str
    model: str
    reasoning_effort: str | None


def agent_model_choices() -> tuple[ModelChoice, ...]:
    """The models a pipeline may pick.

    A model behind an access flag is left out, because the training task is internal and no
    person's flag decides whether it may run.
    """
    return tuple(choice for choice in offered_model_choices() if get_required_model_flag(choice.model) is None)


def resolve_agent_run_config(model: str | None, reasoning_effort: str | None) -> AgentRunConfig:
    """Turn stored settings into what the training task runs with. Blank settings take the defaults.

    A stored model the catalogue no longer serves falls back to the default model, and an
    effort the resolved model does not support falls back to the default effort, so a stale
    row never fails a paid run at dispatch.
    """
    resolved_model = model or AUTORESEARCH_DEFAULT_MODEL
    adapter = get_runtime_adapter_for_model(resolved_model)
    if adapter is None:
        resolved_model = AUTORESEARCH_DEFAULT_MODEL
        adapter = get_runtime_adapter_for_model(resolved_model)
    assert adapter is not None
    resolved_effort = filter_unsupported_effort(
        adapter.value, resolved_model, reasoning_effort
    ) or filter_unsupported_effort(adapter.value, resolved_model, AUTORESEARCH_DEFAULT_REASONING_EFFORT)
    return AgentRunConfig(runtime_adapter=adapter.value, model=resolved_model, reasoning_effort=resolved_effort)


def agent_run_config_for(pipeline: AutoresearchPipeline) -> AgentRunConfig:
    return resolve_agent_run_config(pipeline.agent_model, pipeline.agent_reasoning_effort)


def validate_agent_settings(model: str | None, reasoning_effort: str | None) -> None:
    """Raise ``AgentModelError`` unless the pair may be stored. An effort without a model is checked against the default model."""
    if model is not None and model not in {choice.model for choice in agent_model_choices()}:
        offered = ", ".join(choice.model for choice in agent_model_choices())
        raise AgentModelError(f"Unknown model '{model}'. Choose one of: {offered}.")
    resolved_model = model or AUTORESEARCH_DEFAULT_MODEL
    adapter = get_runtime_adapter_for_model(resolved_model)
    try:
        validate_ai_run_preferences(adapter.value if adapter else None, resolved_model, reasoning_effort)
    except DjangoValidationError as exc:
        raise AgentModelError(" ".join(exc.messages)) from exc
