import pytest

from posthog.hogql import ast

from posthog.hogql_queries.web_analytics.traffic_type import (
    BOT_DEFINITIONS,
    get_bot_name_expr,
    get_bot_type_expr,
    get_traffic_category_expr,
    get_traffic_type_expr,
    is_bot_expr,
)


class TestBotDefinitionsPatterns:
    @pytest.mark.parametrize(
        "pattern,should_match,should_not_match",
        [
            # AI Agents
            ("GPTBot", ["GPTBot/1.0", "GPTBot"], ["Googlebot", "Mozilla/5.0 Chrome"]),
            ("ClaudeBot", ["Mozilla/5.0 ClaudeBot", "ClaudeBot/1.0"], ["Googlebot", "curl/7.64"]),
            ("ChatGPT-User", ["ChatGPT-User"], ["GPTBot", "Googlebot"]),
            ("PerplexityBot", ["PerplexityBot/1.0", "PerplexityBot"], ["Googlebot", "curl/7.64"]),
            # Search Crawlers
            ("Googlebot", ["Googlebot/2.1", "Mozilla/5.0 compatible Googlebot"], ["GPTBot", "curl/7.64"]),
            ("Bingbot", ["Mozilla/5.0 compatible Bingbot", "Bingbot/2.0"], ["Googlebot", "GPTBot"]),
            ("YandexBot", ["YandexBot/3.0", "YandexBot"], ["Googlebot", "GPTBot"]),
            ("Baiduspider", ["Baiduspider/2.0", "Baiduspider"], ["Googlebot", "GPTBot"]),
            # SEO Tools
            ("AhrefsBot", ["AhrefsBot/7.0", "AhrefsBot"], ["Googlebot", "GPTBot"]),
            ("SemrushBot", ["SemrushBot/7.0", "SemrushBot"], ["Googlebot", "GPTBot"]),
            # Social Crawlers
            ("facebookexternalhit", ["facebookexternalhit/1.1", "facebookexternalhit"], ["Googlebot", "GPTBot"]),
            ("Twitterbot", ["Twitterbot/1.0", "Twitterbot"], ["Googlebot", "GPTBot"]),
            ("LinkedInBot", ["LinkedInBot/1.0", "LinkedInBot"], ["Googlebot", "GPTBot"]),
            ("Slackbot", ["Slackbot-LinkExpanding", "Slackbot"], ["Googlebot", "GPTBot"]),
            # Monitoring
            ("Pingdom", ["Pingdom.com_bot", "Pingdom"], ["Googlebot", "GPTBot"]),
            ("UptimeRobot", ["UptimeRobot/2.0", "UptimeRobot"], ["Googlebot", "GPTBot"]),
            ("Datadog", ["Datadog/Synthetics", "Datadog Agent"], ["Googlebot", "GPTBot"]),
            # HTTP Clients
            ("curl/", ["curl/7.64.1", "curl/8.0"], ["Mozilla/5.0 Chrome", "Googlebot"]),
            ("Wget", ["Wget/1.21", "Wget"], ["Mozilla/5.0 Chrome", "Googlebot"]),
            ("python-requests", ["python-requests/2.25", "python-requests"], ["Mozilla/5.0 Chrome", "Googlebot"]),
            ("axios", ["axios/0.21", "axios/1.0"], ["Mozilla/5.0 Chrome", "Googlebot"]),
            ("Go-http-client", ["Go-http-client/1.1", "Go-http-client/2.0"], ["Mozilla/5.0 Chrome", "Googlebot"]),
            # Headless Browsers
            ("PhantomJS", ["PhantomJS/2.1", "PhantomJS"], ["Mozilla/5.0 Chrome", "Googlebot"]),
            ("HeadlessChrome", ["HeadlessChrome/90.0", "HeadlessChrome"], ["Mozilla/5.0 Chrome", "Googlebot"]),
            ("Puppeteer", ["Puppeteer/10.0", "Puppeteer"], ["Mozilla/5.0 Chrome", "Googlebot"]),
            ("Playwright", ["Playwright/1.15", "Playwright"], ["Mozilla/5.0 Chrome", "Googlebot"]),
        ],
    )
    def test_pattern_matches(self, pattern: str, should_match: list[str], should_not_match: list[str]):
        import re

        for ua in should_match:
            assert re.search(pattern, ua), f"Pattern '{pattern}' should match '{ua}'"

        for ua in should_not_match:
            assert not re.search(pattern, ua), f"Pattern '{pattern}' should NOT match '{ua}'"


class TestTrafficTypeExpressions:
    def test_traffic_type_expr_structure(self):
        user_agent_expr = ast.Field(chain=["properties", "$user_agent"])
        expr = get_traffic_type_expr(user_agent_expr)

        # Uses if(multiMatchAnyIndex(...) = 0, default, labels[index]) pattern
        assert isinstance(expr, ast.Call)
        assert expr.name == "if"
        assert len(expr.args) == 3
        # Default value for regular traffic
        assert isinstance(expr.args[1], ast.Constant)
        assert expr.args[1].value == "Regular"

    def test_traffic_category_expr_structure(self):
        user_agent_expr = ast.Field(chain=["properties", "$user_agent"])
        expr = get_traffic_category_expr(user_agent_expr)

        # Uses if(multiMatchAnyIndex(...) = 0, default, labels[index]) pattern
        assert isinstance(expr, ast.Call)
        assert expr.name == "if"
        assert len(expr.args) == 3
        # Default value for regular traffic
        assert isinstance(expr.args[1], ast.Constant)
        assert expr.args[1].value == "regular"

    def test_is_bot_expr_structure(self):
        user_agent_expr = ast.Field(chain=["properties", "$user_agent"])
        expr = is_bot_expr(user_agent_expr)

        assert isinstance(expr, ast.Or)
        # Should have len(BOT_DEFINITIONS) + 1 (empty UA) match conditions
        assert len(expr.exprs) == len(BOT_DEFINITIONS) + 1

    def test_get_bot_type_expr_structure(self):
        user_agent_expr = ast.Field(chain=["properties", "$user_agent"])
        expr = get_bot_type_expr(user_agent_expr)

        # Uses if(multiMatchAnyIndex(...) = 0, default, labels[index]) pattern
        assert isinstance(expr, ast.Call)
        assert expr.name == "if"
        assert len(expr.args) == 3
        # Default value for regular traffic (empty string)
        assert isinstance(expr.args[1], ast.Constant)
        assert expr.args[1].value == ""

    def test_get_bot_name_expr_structure(self):
        user_agent_expr = ast.Field(chain=["properties", "$user_agent"])
        expr = get_bot_name_expr(user_agent_expr)

        # Uses if(multiMatchAnyIndex(...) = 0, default, labels[index]) pattern
        assert isinstance(expr, ast.Call)
        assert expr.name == "if"
        assert len(expr.args) == 3
        # Default value for regular traffic (empty string)
        assert isinstance(expr.args[1], ast.Constant)
        assert expr.args[1].value == ""
