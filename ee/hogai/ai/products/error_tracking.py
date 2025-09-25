from products.error_tracking.backend.max_tools import ErrorTrackingIssueFilteringTool, ErrorTrackingIssueImpactTool

from ee.hogai.ai.product_base import AIProduct


class ErrorTrackingAIProduct(AIProduct):
    name = "error_tracking"
    routing_prompt = "Use when working with error tracking filters or impact."
    # TODO: Populate concise JTBD/workflow system_prompt when product enable/disable is active
    system_prompt = ""
    tools = [
        ErrorTrackingIssueFilteringTool,
        ErrorTrackingIssueImpactTool,
    ]
