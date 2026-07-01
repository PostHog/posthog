from typing import Any, Literal

from django.db import models

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvaluationType(models.TextChoices):
    """How the evaluation is performed"""

    LLM_JUDGE = "llm_judge", "LLM as a judge"
    HOG = "hog", "Hog"
    SENTIMENT = "sentiment", "Sentiment analysis"


class OutputType(models.TextChoices):
    """What type of result is expected"""

    BOOLEAN = "boolean", "Boolean (Pass/Fail)"
    SENTIMENT = "sentiment", "Sentiment"


class LLMJudgeConfig(BaseModel):
    """Configuration for LLM judge evaluations"""

    prompt: str = Field(..., min_length=1, description="Evaluation criteria prompt")

    @field_validator("prompt")
    @classmethod
    def validate_prompt_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Prompt cannot be empty")
        return v.strip()


class HogEvalConfig(BaseModel):
    """Configuration for Hog code evaluations"""

    source: str = Field(..., min_length=1, description="Hog source code")
    bytecode: list[Any] = Field(default_factory=list, description="Compiled bytecode (set automatically on save)")

    @field_validator("source")
    @classmethod
    def validate_source_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Source code cannot be empty")
        return v


class BooleanOutputConfig(BaseModel):
    """Configuration for boolean output type"""

    allows_na: bool = False


class SentimentEvalConfig(BaseModel):
    """Configuration for sentiment evaluations."""

    source: Literal["user_messages"] = Field(
        default="user_messages",
        description="Text source used for sentiment classification.",
    )


class SentimentOutputConfig(BaseModel):
    """Configuration for sentiment output type."""


# Trace-target aggregation window: how long to wait after the first matching generation before
# pulling the whole trace and evaluating it. The default is intentionally generous — even heavy
# tool-using turns settle well under it — while the floor stays low so local testing doesn't
# require waiting half an hour. The workflow re-clamps to the same ceiling as a safety net.
TRACE_EVAL_DEFAULT_WINDOW_SECONDS = 30 * 60
TRACE_EVAL_MIN_WINDOW_SECONDS = 10
TRACE_EVAL_MAX_WINDOW_SECONDS = 2 * 60 * 60


class TraceTargetConfig(BaseModel):
    """Configuration for trace-target evaluations."""

    model_config = ConfigDict(extra="forbid")

    window_seconds: int = Field(
        default=TRACE_EVAL_DEFAULT_WINDOW_SECONDS,
        ge=TRACE_EVAL_MIN_WINDOW_SECONDS,
        le=TRACE_EVAL_MAX_WINDOW_SECONDS,
        description="Seconds to wait after the first matching generation before evaluating the whole trace.",
    )


def validate_target_config(target: str, target_config: dict) -> dict:
    """Validate target_config based on target.

    Trace targets carry a `{window_seconds}` config (defaulted when absent). Every other target
    (generation today) carries no config, so its bag is normalized to empty — this also strips a
    stale window if a user switches a trace eval back to generation.
    """
    if target == "trace":
        try:
            return TraceTargetConfig(**(target_config or {})).model_dump()
        except Exception as e:
            raise ValueError(f"Invalid target_config for trace: {str(e)}") from e
    return {}


# Mapping: (evaluation_type, output_type) -> (evaluation_config_model, output_config_model)
EVALUATION_CONFIG_MODELS: dict[tuple[str, str], tuple[type[BaseModel], type[BaseModel]]] = {
    (EvaluationType.LLM_JUDGE.value, OutputType.BOOLEAN.value): (LLMJudgeConfig, BooleanOutputConfig),
    (EvaluationType.HOG.value, OutputType.BOOLEAN.value): (HogEvalConfig, BooleanOutputConfig),
    (EvaluationType.SENTIMENT.value, OutputType.SENTIMENT.value): (SentimentEvalConfig, SentimentOutputConfig),
}

EVALUATION_CONFIG_CONTENT_KEYS: dict[str, str] = {
    EvaluationType.LLM_JUDGE.value: "prompt",
    EvaluationType.HOG.value: "source",
    EvaluationType.SENTIMENT.value: "source",
}

REPORTABLE_OUTPUT_TYPES: tuple[str, ...] = (OutputType.BOOLEAN.value,)


def evaluation_uses_model_configuration(evaluation_type: str | None) -> bool:
    return evaluation_type == EvaluationType.LLM_JUDGE.value


def evaluation_supports_reports(output_type: str | None) -> bool:
    return output_type in REPORTABLE_OUTPUT_TYPES


def get_evaluation_config_content_key(evaluation_type: str | None) -> str | None:
    return EVALUATION_CONFIG_CONTENT_KEYS.get(evaluation_type) if evaluation_type is not None else None


def evaluation_configs_allow_empty(evaluation_type: str, output_type: str) -> bool:
    config_models = EVALUATION_CONFIG_MODELS.get((evaluation_type, output_type))
    if config_models is None:
        return False

    return all(
        not field_info.is_required()
        for config_model in config_models
        for field_info in config_model.model_fields.values()
    )


def validate_evaluation_configs(
    evaluation_type: str, output_type: str, evaluation_config: dict, output_config: dict
) -> tuple[dict, dict]:
    """
    Validate evaluation_config and output_config based on evaluation_type + output_type combination.

    Returns tuple of (validated_evaluation_config, validated_output_config)
    """
    key = (evaluation_type, output_type)
    if key not in EVALUATION_CONFIG_MODELS:
        raise ValueError(f"Unsupported combination: {evaluation_type} + {output_type}")

    eval_model, output_model = EVALUATION_CONFIG_MODELS[key]

    try:
        validated_eval_config = eval_model(**evaluation_config)
        validated_output_config = output_model(**output_config)
        return validated_eval_config.model_dump(exclude_none=True), validated_output_config.model_dump(
            exclude_none=True
        )
    except Exception as e:
        raise ValueError(f"Invalid config for {evaluation_type}/{output_type}: {str(e)}") from e
