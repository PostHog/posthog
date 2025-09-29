from products.error_tracking.backend.max_tools import ErrorTrackingIssueFilteringTool, ErrorTrackingIssueImpactTool

from ee.hogai.ai.products_infrastructure import AIProduct


class ErrorTrackingAIProduct(AIProduct):
    """Error tracking product for issue filtering and impact analysis."""

    name = "error_tracking"
    routing_prompt = "Use when working with error tracking filters or impact."
    # TODO: Populate concise JTBD/workflow system_prompt when product enable/disable is active
    system_prompt = ""
    tools = [
        ErrorTrackingIssueFilteringTool,
        ErrorTrackingIssueImpactTool,
    ]
