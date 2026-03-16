from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from posthog.schema import AssistantTool

from ee.hogai.tool import MaxTool


class PostHogProduct(StrEnum):
    PRODUCT_ANALYTICS = "product_analytics"
    SESSION_REPLAY = "session_replay"
    FEATURE_FLAGS = "feature_flags"
    EXPERIMENTS = "experiments"
    SURVEYS = "surveys"
    WEB_ANALYTICS = "web_analytics"
    ERROR_TRACKING = "error_tracking"
    DATA_WAREHOUSE = "data_warehouse"
    LLM_ANALYTICS = "llm_analytics"
    WORKFLOWS = "workflows"


class RecommendProductsArgs(BaseModel):
    products: list[PostHogProduct] = Field(
        description="List of PostHog products to recommend based on the user's needs"
    )
    reasoning: str = Field(
        description="Brief explanation of why these products are recommended based on the user's needs"
    )


class RecommendProductsTool(MaxTool):
    """
    Tool for the onboarding agent to recommend PostHog products.
    Returns structured product recommendations that can be parsed by the frontend.
    """

    name: Literal[AssistantTool.RECOMMEND_PRODUCTS] = AssistantTool.RECOMMEND_PRODUCTS
    description: str = (
        "Use this tool to recommend PostHog products to the user. "
        "Call this tool immediately when the user gives any signal about their needs. "
        "The products will be displayed to the user in a structured format."
    )
    args_schema: type[BaseModel] = RecommendProductsArgs

    async def _arun_impl(self, products: list[PostHogProduct], reasoning: str) -> tuple[str, dict]:
        artifact = {
            "products": [p.value for p in products],
            "reasoning": reasoning,
        }

        return (
            f"Recommended products: {', '.join(p.value for p in products)}. {reasoning}",
            artifact,
        )
