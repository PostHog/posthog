import pytest

from products.customer_analytics.backend.logic.agent_tool_access import classify_agent_tool_access


@pytest.mark.parametrize(
    "tool,expected",
    [
        ("execute-sql", "read"),
        ("read-data-schema", "read"),
        ("insight-get", "read"),
        ("feature-flag-get-all", "read"),
        ("persons-list", "read"),
        ("query-trends", "read"),
        ("experiment-results-get", "read"),
        ("create-feature-flag", "write"),
        ("dashboard-create-tile", "write"),
        ("cohorts-partial-update", "write"),
        ("survey-delete", "write"),
        ("dashboard-get-and-update", "write"),
        ("Insight-Update", "write"),
        ("switch-project", "other"),
        ("", "other"),
        (None, "other"),
    ],
)
def test_classify_agent_tool_access(tool: str | None, expected: str) -> None:
    assert classify_agent_tool_access(tool) == expected
