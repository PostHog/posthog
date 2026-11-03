from typing import Any, Literal

from pydantic import BaseModel, Field

from products.ai_observability.backend.models.evaluation_configs import (
    SESSION_EVAL_DEFAULT_QUIET_PERIOD_SECONDS,
    SESSION_EVAL_MAX_QUIET_PERIOD_SECONDS,
    SESSION_EVAL_MIN_QUIET_PERIOD_SECONDS,
    TRACE_EVAL_DEFAULT_WINDOW_SECONDS,
    TRACE_EVAL_MAX_WINDOW_SECONDS,
    TRACE_EVAL_MIN_WINDOW_SECONDS,
)

OutputType = Literal["boolean", "numeric", "categorical"]
Target = Literal["generation", "trace", "session"]


class EvaluationShapeArgs(BaseModel):
    """Arguments shared by the Hog test tool and the create tool, so the agent creates exactly what it tested."""

    output_type: OutputType = Field(default="boolean", description="The evaluation result type")
    output_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Output settings: allows_na, and true_is_failure for boolean; min, max, step and passing_rule for numeric; options, selection_mode and passing categories for categorical",
    )
    target: Target = Field(
        default="generation",
        description=(
            "What one run scores: 'generation' (individual generations), 'trace' (whole traces), "
            "or 'session' (whole sessions that have gone quiet)."
        ),
    )
    window_seconds: int = Field(
        default=TRACE_EVAL_DEFAULT_WINDOW_SECONDS,
        ge=TRACE_EVAL_MIN_WINDOW_SECONDS,
        le=TRACE_EVAL_MAX_WINDOW_SECONDS,
        description="For trace targets: aggregation window, in seconds",
    )
    quiet_period_seconds: int = Field(
        default=SESSION_EVAL_DEFAULT_QUIET_PERIOD_SECONDS,
        ge=SESSION_EVAL_MIN_QUIET_PERIOD_SECONDS,
        le=SESSION_EVAL_MAX_QUIET_PERIOD_SECONDS,
        description="For session targets: how long a session must be inactive before it is scored, in seconds",
    )
