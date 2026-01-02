from typing import Literal

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field
from rest_framework import request, response, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin

from ee.hogai.llm import MaxChatOpenAI

logger = structlog.get_logger(__name__)

# Valid product keys that can be recommended
ProductKeyLiteral = Literal[
    "product_analytics",
    "web_analytics",
    "session_replay",
    "feature_flags",
    "experiments",
    "surveys",
    "error_tracking",
    "data_warehouse",
    "llm_analytics",
]

VALID_PRODUCTS: list[ProductKeyLiteral] = [
    "product_analytics",
    "web_analytics",
    "session_replay",
    "feature_flags",
    "experiments",
    "surveys",
    "error_tracking",
    "data_warehouse",
    "llm_analytics",
]

SYSTEM_PROMPT = """You are an onboarding assistant for PostHog, an open-source product analytics platform.

PostHog is an all-in-one platform that helps companies understand user behavior and build better products.
Unlike point solutions, PostHog combines multiple tools in one platform with a single SDK integration,
so teams can analyze user behavior, debug issues, test changes, and collect feedback without juggling multiple vendors.

Your task is to recommend which PostHog products a new user should start with based on their goals.
Recommend 1-4 products that best match their needs. Don't overwhelm them - fewer is often better for getting started.

Available products:

1. product_analytics -  Track custom events, build funnels, analyze retention, and understand user journeys.
   Best for: Understanding how users interact with your product, measuring conversion, finding drop-off points, create user segments.

2. web_analytics - Privacy-friendly, cookie-free website analytics. Track pageviews, sessions, traffic sources and website performance.
   Best for: Marketing teams, content sites, landing pages, web vitals, replacing Google Analytics.

3. session_replay - Watch recordings of real user sessions to see exactly what users do.
   Best for: Debugging UX issues, understanding confusing flows, seeing why users drop off.

4. feature_flags - Control feature rollouts with targeting rules. No deploys needed to toggle features.
   Best for: Gradual rollouts, beta testing, kill switches, targeting specific user segments.

5. experiments - Run A/B tests with statistical rigor. Integrates with feature flags.
   Best for: Testing hypotheses, optimizing conversion, data-driven product decisions.

6. surveys - Collect qualitative feedback with in-app surveys triggered by user behavior.
   Best for: NPS, user research, understanding the "why" behind user behavior.

7. error_tracking - Monitor exceptions and errors with full stack traces and session context.
   Best for: Debugging production issues, monitoring app health, prioritizing bug fixes.

8. data_warehouse - Query external data sources (Stripe, Hubspot, Postgres, etc.) alongside PostHog data.
   Best for: Advanced analysis, combining product data with revenue/CRM data, custom reporting.

9. llm_analytics - Monitor LLM/AI application performance, costs, and quality.
   Best for: Teams building AI features, tracking token usage, evaluating model outputs.

Guidelines:
- Product analytics is the foundation - recommend it for most users unless they have a very specific need.
- Consider natural pairings: session_replay + error_tracking for debugging, feature_flags + experiments for testing.
- If someone mentions AI/LLM, definitely include llm_analytics.
- Be concise in your reasoning - one or two sentences explaining why these products fit their needs.
"""


class ProductRecommendationResponse(BaseModel):
    """Structured response for product recommendations."""

    model_config = ConfigDict(extra="forbid")

    products: list[ProductKeyLiteral] = Field(
        description="List of recommended product keys (maximum 4)",
        max_length=4,
    )
    reasoning: str = Field(
        description="Brief explanation of why these products are recommended (1-2 sentences)",
    )


class OnboardingViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["POST"])
    def recommend_products(self, request: request.Request, *args, **kwargs) -> response.Response:
        description = request.data.get("description", "")
        browsing_history = request.data.get("browsing_history", [])

        if not description and not browsing_history:
            return response.Response(
                {"error": "Either description or browsing_history is required"},
                status=400,
            )

        # Build user message
        user_parts = []
        if description:
            user_parts.append(f"User's goal: {description}")
        if browsing_history:
            user_parts.append(f"Pages they browsed on posthog.com: {', '.join(browsing_history)}")

        user_message = "\n".join(user_parts)

        try:
            llm = MaxChatOpenAI(
                model="gpt-4.1-mini",
                temperature=0.1,
                user=request.user,
                team=self.team,
                billable=False,
                inject_context=False,
                posthog_properties={
                    "ai_product": "onboarding",
                    "ai_feature": "recommend_products",
                },
            ).with_structured_output(
                ProductRecommendationResponse,
                method="json_schema",
                include_raw=False,
            )

            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=user_message),
            ]

            result: ProductRecommendationResponse = llm.invoke(messages)

            # Filter to only valid products and limit to 4
            valid_products = [p for p in result.products if p in VALID_PRODUCTS][:4]

            return response.Response(
                {
                    "products": valid_products,
                    "reasoning": result.reasoning,
                }
            )

        except Exception as e:
            logger.exception("Error in product recommendation", error=str(e), team_id=self.team.id)
            return response.Response(
                {"error": str(e)},
                status=500,
            )
