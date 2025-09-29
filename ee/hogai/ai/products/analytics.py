from products.data_warehouse.backend.hogql_fixer_ai import HogQLQueryFixerTool
from products.product_analytics.backend.max_tools import EditCurrentInsightTool

from ee.hogai.ai.products_infrastructure import AIProduct


class AnalyticsAIProduct(AIProduct):
    """Analytics product for insights, trends, funnels, and HogQL."""

    name = "analytics"
    routing_prompt = "Use when working with insights, trends, funnels, retention, dashboards, or fixing HogQL."
    system_prompt = """
    <job-to-be-done>
    Work with analytics insights and dashboards, and fix HogQL queries when broken.
    <workflow>
    - create_and_query_insight: update or create insights, visualize data
    - fix_hogql_query: repair invalid HogQL queries
    </workflow>
    </job-to-be-done>
    """.strip()
    tools = [
        EditCurrentInsightTool,
        HogQLQueryFixerTool,
    ]
