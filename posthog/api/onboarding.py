from typing import TYPE_CHECKING, TypedDict, cast

import structlog
from pydantic import BaseModel, ConfigDict, Field
from rest_framework import request, response, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from posthog.schema import WebsiteBrowsingHistoryProdInterest

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception
from posthog.llm.gateway_client import get_llm_client
from posthog.rate_limit import OnboardingIPThrottle

if TYPE_CHECKING:
    from posthog.models import User

logger = structlog.get_logger(__name__)

Product = WebsiteBrowsingHistoryProdInterest


class ProductInfo(TypedDict):
    description: str
    best_for: str


PRODUCTS: dict[Product, ProductInfo | None] = {
    Product.PRODUCT_ANALYTICS: {
        "description": "Track custom events, build funnels, analyze retention, and understand user journeys.",
        "best_for": "Understanding how users interact with your product, measuring conversion, finding drop-off points, create user segments.",
    },
    Product.WEB_ANALYTICS: {
        "description": "Privacy-friendly, cookie-free website analytics. Track pageviews, sessions, traffic sources and website performance.",
        "best_for": "Marketing teams, content sites, landing pages, web vitals, replacing Google Analytics.",
    },
    Product.SESSION_REPLAY: {
        "description": "Watch recordings of real user sessions to see exactly what users do.",
        "best_for": "Debugging UX issues, understanding confusing flows, seeing why users drop off.",
    },
    Product.FEATURE_FLAGS: {
        "description": "Control feature rollouts with targeting rules. No deploys needed to toggle features.",
        "best_for": "Gradual rollouts, beta testing, kill switches, targeting specific user segments.",
    },
    Product.EXPERIMENTS: {
        "description": "Run A/B tests with statistical rigor. Integrates with feature flags.",
        "best_for": "Testing hypotheses, optimizing conversion, data-driven product decisions.",
    },
    Product.SURVEYS: {
        "description": "Collect qualitative feedback with in-app surveys triggered by user behavior.",
        "best_for": 'NPS, user research, understanding the "why" behind user behavior.',
    },
    Product.ERROR_TRACKING: {
        "description": "Monitor exceptions and errors with full stack traces and session context.",
        "best_for": "Debugging production issues, monitoring app health, prioritizing bug fixes.",
    },
    Product.DATA_WAREHOUSE: {
        "description": "Query external data sources (Stripe, Hubspot, Postgres, etc.) alongside PostHog data.",
        "best_for": "Advanced analysis, combining product data with revenue/CRM data, custom reporting.",
    },
    Product.LLM_ANALYTICS: {
        "description": "Monitor LLM/AI application performance, costs, and quality.",
        "best_for": "Teams building AI features, tracking token usage, evaluating model outputs.",
    },
    Product.REVENUE_ANALYTICS: None,
    Product.WORKFLOWS: None,
    Product.LOGS: None,
    Product.ENDPOINTS: None,
}

# Assert we are listing all products that are being included on the website for docs
# Some of them will not have any description because they aren't present on the onboarding flow and will be added later on
# but we should guarantee we're at least aware that they're missing
# This is easily solved in TypeScript using the `Record` type but it doesn't exist in Python
assert set(PRODUCTS.keys()) == set(Product), "PRODUCTS must contain all Product enum members"

VALID_PRODUCTS: set[Product] = {p for p, info in PRODUCTS.items() if info is not None}


def _build_products_prompt() -> str:
    lines = []
    for i, product in enumerate(VALID_PRODUCTS, 1):
        info = PRODUCTS[product]
        assert info is not None

        lines.append(f"{i}. {product.value} - {info['description']}")
        lines.append(f"   Best for: {info['best_for']}")
        lines.append("")
    return "\n".join(lines)


SYSTEM_PROMPT = f"""You are an onboarding assistant for PostHog, an open-source product analytics platform.

PostHog is an all-in-one platform that helps companies understand user behavior and build better products.
Unlike point solutions, PostHog combines multiple tools in one platform with a single SDK integration,
so teams can analyze user behavior, debug issues, test changes, and collect feedback without juggling multiple vendors.

Your task is to recommend which PostHog products a new user should start with based on their goals.
Recommend 1-4 products that best match their needs. Don't overwhelm them - fewer is often better for getting started.

Available products:

{_build_products_prompt()}
Guidelines:
- Product analytics is the foundation - recommend it for most users UNLESS they ask something very specific.
- Consider natural pairings: session_replay + error_tracking for debugging, feature_flags + experiments for testing.
- If someone mentions AI/LLM, definitely include llm_analytics.
- Be concise in your reasoning - one or two sentences explaining why these products fit their needs.
"""

PRODUCTS_LIMIT: int = 3


class ProductRecommendationResponse(BaseModel):
    """Structured response for product recommendations."""

    model_config = ConfigDict(extra="forbid")

    products: list[Product] = Field(
        description="List of recommended product keys (maximum 4)",
        max_length=PRODUCTS_LIMIT,
    )
    reasoning: str = Field(
        description="Brief explanation of why these products are recommended (1-2 sentences)",
    )


class OnboardingViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]
    throttle_classes = [OnboardingIPThrottle]

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
            user_distinct_id = cast("User", request.user).distinct_id
            client = get_llm_client("growth")
            model = "gpt-5-mini"

            logger.debug(
                "Making LLM request for product recommendation",
                team_id=self.team.id,
                user_distinct_id=user_distinct_id,
                model=model,
            )

            completion = client.beta.chat.completions.parse(
                model=model,
                temperature=1,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                user=user_distinct_id,  # type: ignore[arg-type]
                response_format=ProductRecommendationResponse,
            )

            logger.debug(
                "LLM request completed",
                team_id=self.team.id,
                user_distinct_id=user_distinct_id,
                model_used=completion.model,
                usage=completion.usage.model_dump() if completion.usage else None,
            )

            result = completion.choices[0].message.parsed
            if result is None:
                raise ValueError("Failed to parse LLM response")

            valid_products = [p for p in result.products if p in VALID_PRODUCTS][:PRODUCTS_LIMIT]

            return response.Response(
                {
                    "products": [p.value for p in valid_products],
                    "reasoning": result.reasoning,
                }
            )

        except Exception as e:
            logger.exception("Error in product recommendation", error=str(e), team_id=self.team.id)
            capture_exception(
                e, {"team_id": self.team.id, "description": description, "browsing_history": browsing_history}
            )

            return response.Response({"error": "Error in product recommendation"}, status=500)
