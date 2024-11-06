from typing import Optional

from pydantic import BaseModel

from posthog.schema import AITrendsQuery


class GenerateTrendOutputModel(BaseModel):
    reasoning_steps: Optional[list[str]] = None
    answer: Optional[AITrendsQuery] = None
