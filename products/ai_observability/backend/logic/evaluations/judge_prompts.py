"""The LLM judge's prompts and structured outputs, shared by the evaluation runtime and by eval suggestions,
which calibrates a drafted judge on the requests the accepted evaluation will send."""

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field

from posthog.dataclasses import frozen

from products.ai_observability.backend.logic.message_utils import extract_text_from_messages
from products.ai_observability.backend.models.evaluation_configs import CategoricalOutputConfig, NumericOutputConfig
from products.ai_observability.backend.text_repr.formatters import (
    EVENT_TEXT_MAX_CHARS,
    sanitize_surrogates,
    truncate_by_line_sampling,
)
from products.ai_observability.backend.text_repr.formatters.media_blocks import MediaMarker


class BooleanEvalResult(BaseModel):
    """Structured output for boolean evaluation results"""

    reasoning: str
    verdict: bool


_OUTCOME_ALIASES = {
    "n/a": "not_applicable",
    "na": "not_applicable",
    "notapplicable": "not_applicable",
}


def _normalize_outcome(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    cleaned = value.strip().strip(".").lower().replace("-", "_").replace(" ", "_")
    return _OUTCOME_ALIASES.get(cleaned, cleaned)


class BooleanWithNAEvalResult(BaseModel):
    """Structured output for boolean evaluation results that allow N/A.

    One enum rather than an `applicable` flag beside a nullable `verdict`, because no provider's
    JSON Schema subset expresses "verdict is required when applicable is true", so the two-field
    shape let a model return a combination a validator here then rejected. Anthropic does not
    enforce the enum, which is what `_normalize_outcome` is for.
    """

    reasoning: str
    outcome: Annotated[Literal["pass", "fail", "not_applicable"], BeforeValidator(_normalize_outcome)]

    @property
    def applicable(self) -> bool:
        return self.outcome != "not_applicable"

    @property
    def verdict(self) -> bool | None:
        if self.outcome == "not_applicable":
            return None
        return self.outcome == "pass"


class NumericEvalResult(BaseModel):
    reasoning: str
    score: float = Field(strict=True, allow_inf_nan=False)


class NumericWithNAEvalResult(BaseModel):
    reasoning: str
    score: float | None = Field(strict=True, allow_inf_nan=False)

    @property
    def applicable(self) -> bool:
        return self.score is not None


class CategoricalEvalResult(BaseModel):
    reasoning: str
    categories: list[str]


class CategoricalWithNAEvalResult(BaseModel):
    reasoning: str
    categories: list[str] | None


@frozen
class OutputTypeConfig:
    """Configuration for each evaluation output type"""

    response_format: (
        type[BooleanEvalResult]
        | type[BooleanWithNAEvalResult]
        | type[NumericEvalResult]
        | type[NumericWithNAEvalResult]
        | type[CategoricalEvalResult]
        | type[CategoricalWithNAEvalResult]
    )
    instructions: str


def get_output_type_config(
    allows_na: bool,
    *,
    output_type: str = "boolean",
    output_config: dict[str, Any] | None = None,
) -> OutputTypeConfig:
    """Get the output type configuration based on whether N/A is allowed."""
    if output_type == "categorical":
        config = CategoricalOutputConfig.model_validate(output_config or {})
        options = json.dumps([option.model_dump() for option in config.options])
        count = (
            "exactly one category key" if config.selection_mode == "single" else "zero or more distinct category keys"
        )
        instructions = f"Provide a brief reasoning (1 sentence) and categories containing {count} from these options: {options}. Return keys, not display labels."
        if allows_na:
            instructions += " Return categories=null when the criteria does not apply."
        if config.selection_mode == "multiple":
            instructions += " An empty list means no categories apply."
        return OutputTypeConfig(
            response_format=CategoricalWithNAEvalResult if allows_na else CategoricalEvalResult,
            instructions=instructions,
        )
    if output_type == "numeric":
        numeric_config = NumericOutputConfig.model_validate(output_config or {})
        instructions = "Provide a brief reasoning (1 sentence) and a finite numeric score."
        if numeric_config.min is not None:
            instructions += f" The score must be at least {numeric_config.min}."
        if numeric_config.max is not None:
            instructions += f" The score must be at most {numeric_config.max}."
        if numeric_config.step is not None:
            instructions += f" Suggested score increment: {numeric_config.step}; do not round an otherwise valid score."
        if allows_na:
            instructions += " Return score=null when the criteria does not apply."
        return OutputTypeConfig(
            response_format=NumericWithNAEvalResult if allows_na else NumericEvalResult, instructions=instructions
        )
    if allows_na:
        return OutputTypeConfig(
            response_format=BooleanWithNAEvalResult,
            instructions="""First, determine if this evaluation criteria is applicable to the given input/output. If the criteria doesn't apply to this case mark it as not applicable.

Note: If the criteria above instructs you to return "N/A", "not applicable", or similar, return an outcome of "not_applicable".

Return:
- reasoning: a brief explanation (1 sentence)
- outcome: "pass" if the generation meets the criteria, "fail" if it does not, "not_applicable" if the criteria doesn't apply to this input/output""",
        )
    return OutputTypeConfig(
        response_format=BooleanEvalResult,
        instructions="Provide a brief reasoning (1 sentence) and a boolean verdict (true/false).",
    )


def build_system_prompt(
    prompt: str, allows_na: bool, *, output_type: str = "boolean", output_config: dict[str, Any] | None = None
) -> str:
    """Build the system prompt for the LLM judge."""
    config = get_output_type_config(allows_na, output_type=output_type, output_config=output_config)
    return f"""You are an evaluator. Evaluate the following generation according to this criteria:

{prompt}

{config.instructions}"""


def build_user_prompt(
    input_raw: Any, output_raw: Any, tools_data: str, *, media_marker: MediaMarker | None = None
) -> str | None:
    """The judge's user prompt, or None when the output alone exceeds the judge's text limit."""
    # Render the input first, so its images get the lower numbers in reading order.
    input_text = extract_text_from_messages(input_raw, media_marker)
    output_section = f"\n\nOutput: {extract_text_from_messages(output_raw, media_marker)}"
    context_budget = EVENT_TEXT_MAX_CHARS - len("Input: ") - len(output_section)
    if context_budget < 0:
        return None
    sections = [input_text]
    if tools_data:
        sections.append(f"Tools available:\n{tools_data}")
    # Keep the full answer being graded outside the sampled context.
    context = truncate_by_line_sampling("\n\n".join(sections), context_budget)
    return sanitize_surrogates(f"Input: {context}{output_section}")
