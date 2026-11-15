from pydantic import BaseModel, Field

from products.alerts.backend.judge.contract import AnomalyKind


class LLMDetectionVerdict(BaseModel):
    """The structured output the model must return about the current point of one series."""

    is_anomaly: bool = Field(
        description="True only if the current point genuinely warrants a person's attention, given its history."
    )
    kind: AnomalyKind = Field(
        description="The shape of what the current point shows. Use 'none' when is_anomaly is false."
    )
    rationale: str = Field(
        description=(
            "One or two plain sentences about the current point: what you saw and why it is or isn't unusual. "
            "This is shown to the person who receives the alert."
        )
    )
