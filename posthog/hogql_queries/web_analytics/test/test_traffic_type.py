import pytest

from posthog.hogql import ast

from posthog.hogql_queries.web_analytics.traffic_type import (
    AI_AGENT_PATTERNS,
    HEADLESS_PATTERNS,
    HTTP_CLIENT_PATTERNS,
    MONITORING_PATTERNS,
    SEARCH_BOT_PATTERNS,
    SEO_BOT_PATTERNS,
    SOCIAL_BOT_PATTERNS,
    get_traffic_category_expr,
    get_traffic_type_expr,
)


class TestTrafficTypePatterns:
    """Test that bot/automation patterns match expected user agents."""

    @pytest.mark.parametrize(
        "pattern,should_match,should_not_match",
        [
            (
                AI_AGENT_PATTERNS,
                ["GPTBot/1.0", "Mozilla/5.0 ClaudeBot", "ChatGPT-User", "PerplexityBot"],
                ["Googlebot", "Mozilla/5.0 Chrome", "curl/7.64"],
            ),
            (
                SEARCH_BOT_PATTERNS,
                ["Googlebot/2.1", "Mozilla/5.0 compatible Bingbot", "Yandex", "Baiduspider"],
                ["GPTBot", "curl/7.64", "Mozilla/5.0 Chrome"],
            ),
            (
                SEO_BOT_PATTERNS,
                ["AhrefsBot/7.0", "SemrushBot", "MJ12bot", "DotBot"],
                ["Googlebot", "GPTBot", "curl/7.64"],
            ),
            (
                SOCIAL_BOT_PATTERNS,
                ["facebookexternalhit/1.1", "Twitterbot/1.0", "LinkedInBot", "Slackbot"],
                ["Googlebot", "GPTBot", "curl/7.64"],
            ),
            (
                MONITORING_PATTERNS,
                ["Pingdom.com_bot", "UptimeRobot/2.0", "Site24x7", "Datadog"],
                ["Googlebot", "GPTBot", "Mozilla/5.0 Chrome"],
            ),
            (
                HTTP_CLIENT_PATTERNS,
                ["curl/7.64.1", "wget/1.21", "python-requests/2.25", "axios/0.21", "Go-http-client/1.1"],
                ["Mozilla/5.0 Chrome", "Googlebot", "GPTBot"],
            ),
            (
                HEADLESS_PATTERNS,
                ["PhantomJS/2.1", "HeadlessChrome/90.0", "Puppeteer", "Playwright"],
                ["Mozilla/5.0 Chrome", "Googlebot", "curl/7.64"],
            ),
        ],
    )
    def test_pattern_matches(self, pattern: str, should_match: list[str], should_not_match: list[str]):
        import re

        for ua in should_match:
            assert re.search(pattern, ua), f"Pattern '{pattern}' should match '{ua}'"

        for ua in should_not_match:
            assert not re.search(pattern, ua), f"Pattern '{pattern}' should NOT match '{ua}'"


class TestTrafficTypeExpressions:
    """Test that HogQL expressions are built correctly."""

    def test_traffic_type_expr_structure(self):
        user_agent_expr = ast.Field(chain=["properties", "$user_agent"])
        expr = get_traffic_type_expr(user_agent_expr)

        assert isinstance(expr, ast.Call)
        assert expr.name == "multiIf"
        # Should have pairs of (condition, value) + default
        # 8 categories * 2 + 1 default = 17 args
        assert len(expr.args) == 17

    def test_traffic_category_expr_structure(self):
        user_agent_expr = ast.Field(chain=["properties", "$user_agent"])
        expr = get_traffic_category_expr(user_agent_expr)

        assert isinstance(expr, ast.Call)
        assert expr.name == "multiIf"
        # Should have pairs of (condition, value) + default
        # 8 categories * 2 + 1 default = 17 args
        assert len(expr.args) == 17
