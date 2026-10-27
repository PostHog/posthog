from posthog.dataclasses import frozen
from posthog.models import User

from products.tasks.backend.facade.automatic import plan_billing_available, unattended_run_settings
from products.tasks.backend.facade.model_catalogue import (
    ModelChoice,
    display_name_for_model,
    offered_model_choices,
    runtime_adapter_for,
)

from ..facade.enums import ModelStep, StepBilling
from ..models import BetsSettings

DEFAULT_MODELS: dict[ModelStep, tuple[str, str]] = {
    ModelStep.SCOUT: ("", ""),
    ModelStep.TRACKING: ("gpt-6-luna", "low"),
    ModelStep.IDEA: ("", ""),
}


@frozen
class StepModel:
    step: ModelStep
    model: str
    reasoning_effort: str
    billing: StepBilling
    model_label: str


def choice(settings: BetsSettings, user: User, step: ModelStep) -> StepModel:
    stored = settings.step_models.get(step) or {}
    model, effort = (stored["model"], stored.get("reasoning_effort", "")) if "model" in stored else DEFAULT_MODELS[step]
    billing = stored.get("billing")
    if billing not in StepBilling.values:
        billing = (
            StepBilling.SUBSCRIPTION
            if plan_billing_available(user, runtime_adapter_for(model) or "codex")
            else StepBilling.CREDITS
        )
    return StepModel(
        step=step,
        model=model,
        reasoning_effort=effort,
        billing=StepBilling(billing),
        model_label=display_name_for_model(model) if model else "Project default",
    )


def run_settings(settings: BetsSettings, user: User, step: ModelStep) -> dict[str, str]:
    chosen = choice(settings, user, step)
    return unattended_run_settings(
        team_id=settings.team_id,
        user=user,
        model=chosen.model,
        reasoning_effort=chosen.reasoning_effort,
        billing="subscription" if chosen.billing == StepBilling.SUBSCRIPTION else "credits",
    )


def model_options() -> list[ModelChoice]:
    return list(offered_model_choices())


def plan_available(user: User) -> bool:
    return plan_billing_available(user, "codex")
