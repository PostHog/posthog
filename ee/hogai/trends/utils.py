from typing import Literal, Optional

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field

from posthog.schema import ExperimentalAITrendsQuery


class GenerateTrendOutputModel(BaseModel):
    reasoning_steps: Optional[list[str]]
    answer: ExperimentalAITrendsQuery


class TrendsAgentMessage(BaseMessage):
    type: Literal["trends_agent"] = "trends_agent"
    plan: str = Field(..., description="The plan used to generate the trend")
    content: GenerateTrendOutputModel = Field(..., description="The output of the trend generation")
