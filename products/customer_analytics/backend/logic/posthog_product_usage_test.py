import pytest

from products.customer_analytics.backend.logic.posthog_product_usage import (
    AGENT_CATEGORY_PRODUCTS,
    AGENT_TOOL_RULES,
    OTHER_AGENT_PRODUCT_KEY,
    POSTHOG_PRODUCTS,
    agent_tool_product,
)


@pytest.mark.parametrize(
    "tool,category,expected",
    [
        ("execute-sql", "SQL", "dwh"),
        ("EXECUTE-SQL", None, "dwh"),
        ("insight-get", "Insights & analytics", "pa"),
        ("dashboard-create-tile", None, "pa"),
        ("query-session-recordings-list", "Session replays", "replay"),
        ("feature-flag-get-all", None, "flags"),
        ("experiment-results-get", None, "exp"),
        ("error-tracking-issues-list", None, "errors"),
        ("survey-create", None, "surveys"),
        ("llma-clustering-job-create", "AI observability", "llm"),
        ("renamed-tool", "Feature flags", "flags"),
        ("brand-new-tool", None, OTHER_AGENT_PRODUCT_KEY),
        ("brand-new-tool", "A category nobody mapped", OTHER_AGENT_PRODUCT_KEY),
        (None, None, OTHER_AGENT_PRODUCT_KEY),
    ],
)
def test_agent_tool_product(tool: str | None, category: str | None, expected: str) -> None:
    assert agent_tool_product(tool, category) == expected


def test_every_agent_rule_targets_a_known_product() -> None:
    known = {product.key for product in POSTHOG_PRODUCTS}
    targets = {product for product, _fragments in AGENT_TOOL_RULES} | set(AGENT_CATEGORY_PRODUCTS.values())
    assert targets <= known
    assert OTHER_AGENT_PRODUCT_KEY in known
