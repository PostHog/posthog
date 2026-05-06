import pytest

from posthog.hogql_queries.web_analytics.bot_definitions import BOT_DEFINITIONS


class TestBotDefinitionsDataStructure:
    def test_all_bot_definitions_have_required_fields(self):
        for pattern, bot_def in BOT_DEFINITIONS.items():
            assert bot_def.name, f"Bot definition for {pattern} missing name"
            assert bot_def.category, f"Bot definition for {pattern} missing category"
            assert bot_def.traffic_type, f"Bot definition for {pattern} missing traffic_type"
            assert bot_def.operator, f"Bot definition for {pattern} missing operator"

    def test_traffic_types_are_valid(self):
        valid_types = {"AI Agent", "Bot", "Automation"}
        for pattern, bot_def in BOT_DEFINITIONS.items():
            assert bot_def.traffic_type in valid_types, f"Invalid traffic_type for {pattern}: {bot_def.traffic_type}"

    def test_categories_are_valid(self):
        valid_categories = {
            "ai_crawler",
            "ai_search",
            "ai_assistant",
            "search_crawler",
            "seo_crawler",
            "social_crawler",
            "monitoring",
            "http_client",
            "headless_browser",
        }
        for pattern, bot_def in BOT_DEFINITIONS.items():
            assert bot_def.category in valid_categories, f"Invalid category for {pattern}: {bot_def.category}"

    @pytest.mark.parametrize(
        "pattern,expected_name,expected_category,expected_type",
        [
            # AI Crawlers
            ("GPTBot", "GPTBot", "ai_crawler", "AI Agent"),
            ("Google-CloudVertexBot", "Google Cloud Vertex", "ai_crawler", "AI Agent"),
            ("GoogleOther", "GoogleOther", "ai_crawler", "AI Agent"),
            ("ClaudeBot", "Claude", "ai_crawler", "AI Agent"),
            ("Claude-Web", "Claude Web", "ai_crawler", "AI Agent"),
            ("TikTokSpider", "TikTok AI", "ai_crawler", "AI Agent"),
            ("PetalBot", "Petal", "ai_crawler", "AI Agent"),
            ("Brightbot", "Brightbot", "ai_crawler", "AI Agent"),
            ("Diffbot", "Diffbot", "ai_crawler", "AI Agent"),
            ("Timpibot", "Timpi", "ai_crawler", "AI Agent"),
            ("omgili", "Webz.io", "ai_crawler", "AI Agent"),
            ("Webzio-Extended", "Webz.io Extended", "ai_crawler", "AI Agent"),
            ("Amazonbot", "Amazon", "ai_crawler", "AI Agent"),
            # AI Search
            ("OAI-SearchBot", "OpenAI Search", "ai_search", "AI Agent"),
            ("Claude-SearchBot", "Claude Search", "ai_search", "AI Agent"),
            ("PerplexityBot", "Perplexity", "ai_search", "AI Agent"),
            ("Applebot-Extended", "Apple AI", "ai_search", "AI Agent"),
            ("Applebot/", "Applebot", "ai_search", "AI Agent"),
            # AI Assistants
            ("ChatGPT-User", "ChatGPT", "ai_assistant", "AI Agent"),
            ("Claude-User", "Claude User", "ai_assistant", "AI Agent"),
            ("Perplexity-User", "Perplexity User", "ai_assistant", "AI Agent"),
            ("Meta-ExternalFetcher", "Meta Fetcher", "ai_assistant", "AI Agent"),
            ("DuckAssistBot", "DuckDuckGo AI", "ai_assistant", "AI Agent"),
            ("MistralAI-User", "Mistral AI", "ai_assistant", "AI Agent"),
            # PostHog Code clients
            (r"desktop\.hog\.dev", "PostHog Code Desktop", "ai_assistant", "AI Agent"),
            (r"mobile\.hog\.dev", "PostHog Code Mobile", "ai_assistant", "AI Agent"),
            (r"agent\.hog\.dev", "PostHog Code Agent", "ai_assistant", "AI Agent"),
            (r"cloud\.hog\.dev", "PostHog Code Cloud", "ai_assistant", "AI Agent"),
            # Search Crawlers
            ("Googlebot", "Googlebot", "search_crawler", "Bot"),
            ("bingbot", "Bingbot", "search_crawler", "Bot"),
            # SEO Tools
            ("AhrefsBot", "Ahrefs", "seo_crawler", "Bot"),
            # Social Crawlers
            ("FacebookBot", "Facebook Bot", "social_crawler", "Bot"),
            ("facebookexternalhit", "Facebook", "social_crawler", "Bot"),
            # Monitoring
            ("Datadog", "Datadog", "monitoring", "Bot"),
            # HTTP Clients
            ("curl/", "curl", "http_client", "Automation"),
            # Headless Browsers
            ("HeadlessChrome", "Headless Chrome", "headless_browser", "Automation"),
        ],
    )
    def test_specific_bot_definitions(self, pattern, expected_name, expected_category, expected_type):
        assert pattern in BOT_DEFINITIONS, f"Missing bot definition for {pattern}"
        bot_def = BOT_DEFINITIONS[pattern]
        assert bot_def.name == expected_name
        assert bot_def.category == expected_category
        assert bot_def.traffic_type == expected_type

    def test_longer_patterns_come_before_shorter_substrings(self):
        patterns = list(BOT_DEFINITIONS.keys())
        for i, p1 in enumerate(patterns):
            for j, p2 in enumerate(patterns):
                if i != j and p1 in p2 and len(p1) < len(p2):
                    assert patterns.index(p2) < patterns.index(p1), (
                        f"{p2} must come before {p1} for correct multiMatchAnyIndex matching"
                    )
