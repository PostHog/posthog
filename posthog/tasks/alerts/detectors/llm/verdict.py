from typing import Literal

from pydantic import BaseModel, Field

AnomalyKind = Literal["spike", "drop", "flatline", "trend_break", "level_shift", "pattern_change", "none"]


class LLMDetectionVerdict(BaseModel):
    """The structured output the model must return for one judged series."""

    is_anomaly: bool = Field(
        description="True only if something in this series genuinely warrants a person's attention."
    )
    confidence: float = Field(ge=0.0, le=1.0, description="How confident you are in the verdict, from 0 to 1.")
    kind: AnomalyKind = Field(description="The shape of what you saw. Use 'none' when is_anomaly is false.")
    rationale: str = Field(
        description=(
            "One or two plain sentences naming what you saw and why it is or isn't unusual. "
            "This is shown to the person who receives the alert."
        )
    )
    triggered_indices: list[int] = Field(
        default_factory=list,
        description=(
            "Zero-based indices, into the point table you were given, of every point you consider "
            "anomalous. Empty when is_anomaly is false."
        ),
    )
