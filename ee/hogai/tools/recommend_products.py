from typing import Literal

from pydantic import BaseModel, Field

from posthog.schema import AssistantTool

from ee.hogai.tool import MaxTool


class RecommendProductsArgs(BaseModel):
    products: list[str] = Field(
        description="List of PostHog product keys to recommend. Valid values: product_analytics, session_replay, feature_flags, experiments, surveys, web_analytics, error_tracking, data_warehouse, llm_observability"
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
        "Use this tool to recommend PostHog products to the user based on their needs. "
        "Call this tool when you have enough information to make product recommendations. "
        "The products will be displayed to the user in a structured format."
    )
    args_schema: type[BaseModel] = RecommendProductsArgs

    async def _arun_impl(self, products: list[str], reasoning: str) -> tuple[str, dict]:
        valid_products = {
            "product_analytics",
            "session_replay",
            "feature_flags",
            "experiments",
            "surveys",
            "web_analytics",
            "error_tracking",
            "data_warehouse",
            "llm_observability",
        }

        validated_products = [p for p in products if p in valid_products]

        artifact = {
            "products": validated_products,
            "reasoning": reasoning,
        }

        return (
            f"Recommended products: {', '.join(validated_products)}. {reasoning}",
            artifact,
        )
