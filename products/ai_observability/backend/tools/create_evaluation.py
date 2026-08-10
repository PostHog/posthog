import uuid
from typing import Any, Literal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from pydantic import BaseModel, Field
from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.schema import AssistantTool

from posthog.event_usage import report_user_action
from posthog.sync import database_sync_to_async

from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.evaluation_configs import (
    EvaluationType,
    OutputType,
    evaluation_supports_reports,
)
from products.ai_observability.backend.models.evaluation_reports import EvaluationReport
from products.ai_observability.backend.models.evaluations import Evaluation, EvaluationTarget
from products.ai_observability.backend.models.model_configuration import LLMModelConfiguration
from products.ai_observability.backend.models.provider_keys import LLMProviderKey

from ee.hogai.tool import MaxTool

TOOL_DESCRIPTION = """Save an online evaluation that scores new AI generations, traces, or sessions from now on.

Use this once the user has agreed on what the evaluation should check. For a `hog` evaluation,
run `run_hog_eval_test` first so the source is known to compile and behave as intended.

Evaluation types:
- `hog`: deterministic code in `source`, returning true (pass), false (fail), or null (N/A). Free to run.
- `llm_judge`: an LLM scores each unit against `prompt`. Costs an LLM call per evaluated unit, so it
  needs a provider and model — omit them to use the team's active provider key and its default model.
- `sentiment`: classifies user-message sentiment. Free, and only valid with the `generation` target.

`target` picks the unit under evaluation: `generation` (each matching $ai_generation), `trace`
(the whole trace once it settles), or `session` (the whole $ai_session_id session once it settles).
For trace and session, pass either `window_seconds` (evaluate a fixed time after the first matching
generation) or `quiet_period_seconds` (evaluate once the unit has been inactive that long); leaving
both unset uses the product defaults for that target.

Scope which generations trigger the evaluation with `property_filters` and `rollout_percentage` —
an unfiltered evaluation runs on every generation the project ingests.

Evaluations are created paused unless `enabled` is set, so the user can review one before it starts
running (and, for `llm_judge`, before it starts spending).
"""


class CreateEvaluationArgs(BaseModel):
    name: str = Field(description="Short name for the evaluation, e.g. 'Answer cites a source'")
    evaluation_type: Literal["llm_judge", "hog", "sentiment"] = Field(description="How the evaluation is performed")
    description: str = Field(
        default="",
        description="What this evaluation checks, and why. Shown in the evaluation list.",
    )
    prompt: str | None = Field(
        default=None,
        description="For 'llm_judge': the criteria the judge scores against. Describe what passes and what fails.",
    )
    source: str | None = Field(
        default=None,
        description="For 'hog': the Hog source code, returning true (pass), false (fail), or null (N/A).",
    )
    target: Literal["generation", "trace", "session"] = Field(
        default="generation",
        description="What the evaluation runs on: each generation, each whole trace, or each whole session.",
    )
    window_seconds: int | None = Field(
        default=None,
        description=(
            "For 'trace' and 'session': evaluate this many seconds after the first matching generation. "
            "Mutually exclusive with quiet_period_seconds."
        ),
    )
    quiet_period_seconds: int | None = Field(
        default=None,
        description=(
            "For 'trace' and 'session': evaluate once the unit has had no new activity for this long. "
            "Mutually exclusive with window_seconds."
        ),
    )
    max_age_seconds: int | None = Field(
        default=None,
        description="With quiet_period_seconds: hard cap on the total wait from the first matching generation.",
    )
    allows_na: bool = Field(
        default=False,
        description="Whether the evaluation may return N/A for units it does not apply to.",
    )
    property_filters: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Property filters (same shape as insight filters) scoping which generations trigger the evaluation, "
            "e.g. [{'key': '$ai_span_name', 'value': ['MaxChat'], 'operator': 'exact', 'type': 'event'}]."
        ),
    )
    rollout_percentage: float = Field(
        default=100,
        ge=0,
        le=100,
        description="Sample this percentage of matching units. Use below 100 to cap volume and cost.",
    )
    provider: Literal["openai", "anthropic", "gemini"] | None = Field(
        default=None,
        description="For 'llm_judge': the judge's provider. Defaults to the team's active provider key.",
    )
    model: str | None = Field(
        default=None,
        description="For 'llm_judge': the judge's model. Defaults to the provider's default model.",
    )
    enabled: bool = Field(
        default=False,
        description="Start the evaluation immediately. Leave false to save it paused for the user to review.",
    )


class CreateEvaluationTool(MaxTool):
    name: str = AssistantTool.CREATE_EVALUATION.value
    description: str = TOOL_DESCRIPTION
    args_schema: type[BaseModel] = CreateEvaluationArgs

    def get_required_resource_access(self):
        return [("evaluation", "editor")]

    async def is_dangerous_operation(self, *, enabled: bool = False, **kwargs) -> bool:
        """Saving a paused evaluation is reversible and costs nothing. Starting one means it grades
        every matching unit the project ingests from now on — for an LLM judge, on the team's key."""
        return enabled

    async def format_dangerous_operation_preview(
        self,
        *,
        name: str,
        evaluation_type: str,
        target: str = "generation",
        rollout_percentage: float = 100,
        **kwargs,
    ) -> str:
        scope = f"{rollout_percentage:g}% of {target}s" if rollout_percentage < 100 else f"every {target}"
        lines = [f"Create and start the evaluation “{name}”.", f"It will run on {scope} from now on."]
        if evaluation_type == EvaluationType.LLM_JUDGE.value:
            lines.append("Each run is an LLM call billed to the team's provider key.")
        return "\n".join(lines)

    async def _arun_impl(self, **kwargs) -> tuple[str, None]:
        args = CreateEvaluationArgs(**kwargs)

        if args.evaluation_type == EvaluationType.HOG.value and not (args.source or "").strip():
            return ("A 'hog' evaluation needs `source`. Write the Hog code and test it with run_hog_eval_test.", None)
        if args.evaluation_type == EvaluationType.LLM_JUDGE.value and not (args.prompt or "").strip():
            return ("An 'llm_judge' evaluation needs `prompt` — the criteria the judge scores against.", None)
        if args.evaluation_type == EvaluationType.SENTIMENT.value and args.target != EvaluationTarget.GENERATION.value:
            return ("Sentiment evaluations can only target each generation. Use target='generation'.", None)
        if args.window_seconds is not None and args.quiet_period_seconds is not None:
            return ("Pass either `window_seconds` or `quiet_period_seconds`, not both.", None)

        try:
            evaluation, note = await database_sync_to_async(self._create_evaluation)(args)
        except (DRFValidationError, DjangoValidationError) as e:
            return (f"Could not save the evaluation: {_format_validation_error(e)}", None)

        url = f"/project/{self._team.id}/ai-evals/evaluations/{evaluation.id}"
        state = "running now" if evaluation.enabled else "saved paused - enable it when you're ready"
        lines = [f"Created evaluation '{evaluation.name}' ({evaluation.id}), {state}.", f"Open it at {url}"]
        if note:
            lines.append(note)
        return ("\n".join(lines), None)

    def _create_evaluation(self, args: CreateEvaluationArgs) -> tuple[Evaluation, str | None]:
        model_configuration: LLMModelConfiguration | None = None
        note: str | None = None
        enabled = args.enabled

        # One transaction across the model configuration, the evaluation, and its report, so a
        # rejected evaluation can't leave an orphaned model configuration row behind.
        with transaction.atomic():
            if args.evaluation_type == EvaluationType.LLM_JUDGE.value:
                model_configuration = self._resolve_model_configuration(args)
                if enabled and not self._has_usable_provider_key(model_configuration.provider):
                    # The first run would disable it again anyway. Save it paused and say why, rather
                    # than handing back an evaluation that quietly turns itself off.
                    enabled = False
                    note = (
                        "Saved paused: this project has no working provider API key for "
                        f"{model_configuration.provider}. Add one in AI observability settings, then enable it."
                    )

            evaluation = Evaluation(
                team=self._team,
                created_by=self._user,
                name=args.name,
                description=args.description,
                evaluation_type=args.evaluation_type,
                evaluation_config=_evaluation_config(args),
                output_type=_output_type(args.evaluation_type),
                output_config=_output_config(args),
                target=args.target,
                target_config=_target_config(args),
                conditions=_conditions(args),
                model_configuration=model_configuration,
                enabled=enabled,
            )
            evaluation.save()

            if evaluation_supports_reports(evaluation.output_type, evaluation.target):
                # Mirrors EvaluationViewSet.perform_create, so reports are generated from the start.
                EvaluationReport.objects.get_or_create(evaluation=evaluation, team_id=self._team.id)

        report_user_action(
            self._user,
            "llma evaluation created",
            {
                "evaluation_id": str(evaluation.id),
                "evaluation_name": evaluation.name,
                "evaluation_type": evaluation.evaluation_type,
                "output_type": evaluation.output_type,
                "has_description": bool(evaluation.description),
                "enabled": evaluation.enabled,
                "condition_count": len(evaluation.conditions or []),
                "has_rollout_percentage": args.rollout_percentage < 100,
                "created_via": "max",
            },
            team=self._team,
        )

        return evaluation, note

    def _resolve_model_configuration(self, args: CreateEvaluationArgs) -> LLMModelConfiguration:
        """Pick the judge's provider and model, falling back to the team's active provider key so the
        user doesn't have to name a model to get an evaluation saved."""
        # Widened from the args' Literal: a provider taken from the team's active key is any
        # LLMProvider, not only the three a judge can be configured with directly.
        provider: str | None = args.provider
        model: str | None = args.model

        if provider is None:
            active_key = self._active_provider_key()
            if active_key is None:
                raise DRFValidationError(
                    {
                        "model_configuration": "Choose a provider and model for the judge, or add a provider API key in AI observability settings."
                    }
                )
            provider = active_key.provider

        if model is None:
            model = DEFAULT_MODEL_BY_PROVIDER.get(provider)
            if model is None:
                # The team's active key is for a provider evaluations have no default judge model for.
                raise DRFValidationError(
                    {"model_configuration": f"Pass an explicit provider and model - {provider} has no default."}
                )

        # provider_key is left unpinned: the run resolves the team's active key for this provider,
        # so the evaluation keeps working when the key is rotated.
        model_configuration = LLMModelConfiguration(team=self._team, provider=provider, model=model)
        model_configuration.full_clean()
        model_configuration.save()
        return model_configuration

    def _active_provider_key(self) -> LLMProviderKey | None:
        config = EvaluationConfig.objects.filter(team=self._team).first()
        return config.active_provider_key if config else None

    def _has_usable_provider_key(self, provider: str) -> bool:
        active_key = self._active_provider_key()
        return (
            active_key is not None and active_key.provider == provider and active_key.state == LLMProviderKey.State.OK
        )


def _evaluation_config(args: CreateEvaluationArgs) -> dict[str, Any]:
    if args.evaluation_type == EvaluationType.LLM_JUDGE.value:
        return {"prompt": (args.prompt or "").strip()}
    if args.evaluation_type == EvaluationType.HOG.value:
        return {"source": args.source or ""}
    return {"source": "user_messages"}


def _output_type(evaluation_type: str) -> str:
    if evaluation_type == EvaluationType.SENTIMENT.value:
        return OutputType.SENTIMENT.value
    return OutputType.BOOLEAN.value


def _output_config(args: CreateEvaluationArgs) -> dict[str, Any]:
    if args.evaluation_type == EvaluationType.SENTIMENT.value:
        return {}
    return {"allows_na": args.allows_na}


def _target_config(args: CreateEvaluationArgs) -> dict[str, Any]:
    """Only aggregate targets carry a settle config; the model normalizes the rest and fills defaults."""
    if args.target == EvaluationTarget.GENERATION.value:
        return {}
    if args.window_seconds is not None:
        return {"strategy": "fixed_window", "window_seconds": args.window_seconds}
    if args.quiet_period_seconds is not None or args.max_age_seconds is not None:
        config: dict[str, Any] = {"strategy": "inactivity"}
        if args.quiet_period_seconds is not None:
            config["quiet_period_seconds"] = args.quiet_period_seconds
        if args.max_age_seconds is not None:
            config["max_age_seconds"] = args.max_age_seconds
        return config
    return {}


def _conditions(args: CreateEvaluationArgs) -> list[dict[str, Any]]:
    """One condition set is enough for everything this tool exposes: filters AND together within a
    set, and the rollout percentage is the dispatcher's sampling field."""
    if not args.property_filters and args.rollout_percentage >= 100:
        return []
    return [
        {
            "id": str(uuid.uuid4()),
            "rollout_percentage": args.rollout_percentage,
            "properties": args.property_filters or [],
        }
    ]


def _format_validation_error(error: DRFValidationError | DjangoValidationError) -> str:
    detail = getattr(error, "detail", None) or getattr(error, "message_dict", None) or getattr(error, "messages", None)
    if isinstance(detail, dict):
        return "; ".join(f"{field}: {_flatten(messages)}" for field, messages in detail.items())
    return _flatten(detail if detail is not None else str(error))


def _flatten(messages: Any) -> str:
    if isinstance(messages, list | tuple):
        return " ".join(str(message) for message in messages)
    return str(messages)
