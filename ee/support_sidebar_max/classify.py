"""
Classify support tickets using Anthropic to determine target area, severity, and kind.
"""

import json
import logging

from django.conf import settings

import anthropic
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

logger = logging.getLogger("django")

TARGET_AREAS = {
    "login": "Authentication (incl. login, sign-up, invites)",
    "analytics_platform": "Analytics features (incl. alerts, subscriptions, exports, etc.)",
    "billing": "Billing",
    "cohorts": "Cohorts",
    "data_ingestion": "Data ingestion",
    "data_management": "Data management (incl. events, actions, properties)",
    "mobile": "Mobile",
    "notebooks": "Notebooks",
    "onboarding": "Onboarding",
    "platform_addons": "Platform addons",
    "sdk": "SDK / Implementation",
    "setup-wizard": "Wizard",
    "data_warehouse": "Data warehouse (sources)",
    "data_modeling": "Data modeling (views, matviews, endpoints)",
    "batch_exports": "Destinations (batch exports)",
    "cdp_destinations": "Destinations (real-time)",
    "error_tracking": "Error tracking",
    "experiments": "Experiments",
    "feature_flags": "Feature flags",
    "group_analytics": "Group analytics",
    "customer_analytics": "Customer analytics",
    "llm-analytics": "LLM analytics",
    "logs": "Logs",
    "max-ai": "PostHog AI",
    "mcp-server": "MCP Server",
    "workflows": "Workflows / Messaging",
    "analytics": "Product analytics (incl. insights, dashboards, etc.)",
    "revenue_analytics": "Revenue analytics",
    "session_replay": "Session replay (incl. recordings)",
    "surveys": "Surveys",
    "toolbar": "Toolbar (incl. heatmaps)",
    "web_analytics": "Web analytics",
}

SEVERITY_LEVELS = {
    "critical": "Outage, data loss, or data breach",
    "high": "Feature is not working at all",
    "medium": "Feature not working as expected",
    "low": "Question or feature request",
}

KINDS = {
    "bug": "Bug report — something is broken or not working correctly",
    "feedback": "Feedback — a feature request or suggestion",
    "support": "Support request — a question or need for help",
}

CLASSIFY_PROMPT = """You are a support ticket classifier for PostHog, a product analytics platform.

Given a support ticket message (and optionally the page URL it was submitted from), classify it into three categories.

## Target area
Choose the most relevant product area:
{target_areas}

## Severity level
Choose the severity:
{severity_levels}

## Kind
Choose the ticket type:
{kinds}

Respond with ONLY valid JSON matching this exact schema:
{{"target_area": "<key>", "severity_level": "<key>", "kind": "<key>"}}

Do not include any explanation or other text."""


def _build_prompt() -> str:
    target_area_lines = "\n".join(f'- "{k}": {v}' for k, v in TARGET_AREAS.items())
    severity_lines = "\n".join(f'- "{k}": {v}' for k, v in SEVERITY_LEVELS.items())
    kind_lines = "\n".join(f'- "{k}": {v}' for k, v in KINDS.items())

    return CLASSIFY_PROMPT.format(
        target_areas=target_area_lines,
        severity_levels=severity_lines,
        kinds=kind_lines,
    )


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def classify_ticket(request: Request) -> Response:
    message = request.data.get("message", "").strip()
    if not message:
        return Response({"error": "No message provided"}, status=status.HTTP_400_BAD_REQUEST)

    url_hint = request.data.get("url", "")

    user_content = message
    if url_hint:
        user_content = f"Page URL: {url_hint}\n\nMessage:\n{message}"

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=128,
            system=_build_prompt(),
            messages=[{"role": "user", "content": user_content}],
        )

        text = response.content[0].text.strip()
        result = json.loads(text)

        # Validate the response contains expected keys with valid values
        if result.get("target_area") not in TARGET_AREAS:
            result["target_area"] = None
        if result.get("severity_level") not in SEVERITY_LEVELS:
            result["severity_level"] = None
        if result.get("kind") not in KINDS:
            result["kind"] = "support"

        return Response(result)

    except (json.JSONDecodeError, IndexError, KeyError) as e:
        logger.warning(f"Failed to parse classification response: {e}")
        # Fall back to defaults rather than failing the ticket
        return Response({"target_area": None, "severity_level": None, "kind": "support"})

    except anthropic.RateLimitError:
        logger.warning("Classification rate limited, falling back to defaults")
        return Response({"target_area": None, "severity_level": None, "kind": "support"})

    except Exception as e:
        logger.error(f"Classification error: {e}", exc_info=True)
        # Never block ticket submission — return defaults on any error
        return Response({"target_area": None, "severity_level": None, "kind": "support"})
