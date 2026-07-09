import ipaddress

import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.functions.traffic_type import (
    get_bot_name,
    get_bot_operator,
    get_bot_type,
    get_traffic_category,
    get_traffic_type,
    is_bot,
)
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from products.actions.backend.models.action import Action
from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS
from products.web_analytics.backend.hogql_queries.bot_ip_definitions import BOT_IP_DEFINITIONS


class TestTrafficTypeFunctions:
    def test_get_traffic_type_returns_if_with_array_lookup(self):
        node = ast.Call(name="getTrafficType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_type(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "if"
        assert len(result.args) == 3
        # First arg: comparison (multiMatchAnyIndex(...) = 0)
        assert isinstance(result.args[0], ast.CompareOperation)
        # Second arg: default value
        assert isinstance(result.args[1], ast.Constant)
        assert result.args[1].value == "Regular"
        # Third arg: array access
        assert isinstance(result.args[2], ast.ArrayAccess)

    def test_get_traffic_type_uses_multiMatchAnyIndex(self):
        node = ast.Call(name="getTrafficType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_type(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)

        # Check the comparison contains multiMatchAnyIndex
        comparison = result.args[0]
        assert isinstance(comparison, ast.CompareOperation)
        assert isinstance(comparison.left, ast.Call)
        assert comparison.left.name == "multiMatchAnyIndex"

    def test_get_traffic_type_has_correct_patterns_and_labels(self):
        node = ast.Call(name="getTrafficType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_type(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)

        # Get the multiMatchAnyIndex call from the comparison
        comparison = result.args[0]
        assert isinstance(comparison, ast.CompareOperation)
        index_call = comparison.left
        assert isinstance(index_call, ast.Call)

        # Check patterns array
        patterns_array = index_call.args[1]
        assert isinstance(patterns_array, ast.Array)
        # Should have len(BOT_DEFINITIONS) + 1 (empty UA) patterns
        assert len(patterns_array.exprs) == len(BOT_DEFINITIONS) + 1

        # Get labels from the array access
        array_access = result.args[2]
        assert isinstance(array_access, ast.ArrayAccess)
        labels_array = array_access.array
        assert isinstance(labels_array, ast.Array)

        # Extract label values
        label_values = [expr.value for expr in labels_array.exprs if isinstance(expr, ast.Constant)]
        assert "AI Agent" in label_values
        assert "Bot" in label_values
        assert "Automation" in label_values  # For empty UA

    def test_get_traffic_category_returns_if_with_array_lookup(self):
        node = ast.Call(name="getTrafficCategory", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_category(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "if"
        assert len(result.args) == 3
        # Default should be "regular"
        default_arg = result.args[1]
        assert isinstance(default_arg, ast.Constant)
        assert default_arg.value == "regular"

    def test_get_traffic_category_returns_expected_values(self):
        node = ast.Call(name="getTrafficCategory", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_category(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)

        # Get labels from the array access
        array_access = result.args[2]
        assert isinstance(array_access, ast.ArrayAccess)
        labels_array = array_access.array
        assert isinstance(labels_array, ast.Array)

        label_values = [expr.value for expr in labels_array.exprs if isinstance(expr, ast.Constant)]

        assert "ai_crawler" in label_values
        assert "ai_search" in label_values
        assert "ai_assistant" in label_values
        assert "search_crawler" in label_values
        assert "http_client" in label_values
        assert "no_user_agent" in label_values  # For empty UA


class TestIsBotFunction:
    def test_is_bot_returns_bool_cast(self):
        node = ast.Call(name="isLikelyBot", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = is_bot(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "toBool"
        comparison = result.args[0]
        assert isinstance(comparison, ast.CompareOperation)
        assert comparison.op == ast.CompareOperationOp.NotEq

    def test_is_bot_uses_multiMatchAnyIndex(self):
        node = ast.Call(name="isLikelyBot", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = is_bot(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)
        comparison = result.args[0]
        assert isinstance(comparison, ast.CompareOperation)
        assert isinstance(comparison.left, ast.Call)
        assert comparison.left.name == "multiMatchAnyIndex"

    def test_is_bot_compares_against_zero(self):
        node = ast.Call(name="isLikelyBot", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = is_bot(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)
        comparison = result.args[0]
        assert isinstance(comparison, ast.CompareOperation)
        assert isinstance(comparison.right, ast.Constant)
        assert comparison.right.value == 0


class TestGetBotTypeFunction:
    def test_get_bot_type_returns_if_with_array_lookup(self):
        node = ast.Call(name="getBotType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_bot_type(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "if"
        assert len(result.args) == 3
        # Default should be empty string
        default_arg = result.args[1]
        assert isinstance(default_arg, ast.Constant)
        assert default_arg.value == ""

    def test_get_bot_type_returns_expected_values(self):
        node = ast.Call(name="getBotType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_bot_type(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)

        # Get labels from the array access
        array_access = result.args[2]
        assert isinstance(array_access, ast.ArrayAccess)
        labels_array = array_access.array
        assert isinstance(labels_array, ast.Array)

        label_values = [expr.value for expr in labels_array.exprs if isinstance(expr, ast.Constant)]

        assert "ai_crawler" in label_values
        assert "ai_search" in label_values
        assert "ai_assistant" in label_values
        assert "search_crawler" in label_values
        assert "seo_crawler" in label_values
        assert "social_crawler" in label_values
        assert "monitoring" in label_values
        assert "http_client" in label_values
        assert "headless_browser" in label_values
        assert "no_user_agent" in label_values


class TestGetBotNameFunction:
    def test_get_bot_name_returns_if_with_array_lookup(self):
        node = ast.Call(name="getBotName", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_bot_name(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "if"
        assert len(result.args) == 3
        # Default should be empty string
        default_arg = result.args[1]
        assert isinstance(default_arg, ast.Constant)
        assert default_arg.value == ""

    def test_get_bot_name_returns_expected_values(self):
        node = ast.Call(name="getBotName", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_bot_name(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)

        # Get labels from the array access
        array_access = result.args[2]
        assert isinstance(array_access, ast.ArrayAccess)
        labels_array = array_access.array
        assert isinstance(labels_array, ast.Array)

        label_values = [expr.value for expr in labels_array.exprs if isinstance(expr, ast.Constant)]

        # Check some expected bot names
        assert "Googlebot" in label_values
        assert "ChatGPT" in label_values
        assert "Claude" in label_values
        assert "curl" in label_values
        # Empty string for regular traffic and empty UA
        assert "" in label_values

    def test_get_bot_name_preserves_user_agent_expression(self):
        node = ast.Call(name="test", args=[])
        user_agent_arg = ast.Field(chain=["custom", "user_agent_field"])

        result = get_bot_name(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "if"
        # multiMatchAnyIndex should use our custom user agent field wrapped in ifNull
        comparison = result.args[0]
        assert isinstance(comparison, ast.CompareOperation)
        index_call = comparison.left
        assert isinstance(index_call, ast.Call)
        # First arg is ifNull(user_agent, '')
        safe_user_agent = index_call.args[0]
        assert isinstance(safe_user_agent, ast.Call)
        assert safe_user_agent.name == "ifNull"
        assert safe_user_agent.args[0] == user_agent_arg


class TestTrafficTypeFunctionPatterns:
    @pytest.mark.parametrize(
        "function_builder,expected_default",
        [
            (get_traffic_type, "Regular"),
            (get_traffic_category, "regular"),
            (get_bot_type, ""),
            (get_bot_name, ""),
        ],
    )
    def test_functions_preserve_user_agent_expression(self, function_builder, expected_default):
        node = ast.Call(name="test", args=[])
        user_agent_arg = ast.Field(chain=["custom", "user_agent_field"])

        result = function_builder(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "if"
        # Default value
        default_arg = result.args[1]
        assert isinstance(default_arg, ast.Constant)
        assert default_arg.value == expected_default
        # multiMatchAnyIndex should use our custom user agent field wrapped in ifNull
        comparison = result.args[0]
        assert isinstance(comparison, ast.CompareOperation)
        index_call = comparison.left
        assert isinstance(index_call, ast.Call)
        assert index_call.name == "multiMatchAnyIndex"
        # First arg is ifNull(user_agent, '')
        safe_user_agent = index_call.args[0]
        assert isinstance(safe_user_agent, ast.Call)
        assert safe_user_agent.name == "ifNull"
        assert safe_user_agent.args[0] == user_agent_arg

    def test_is_bot_preserves_user_agent_expression(self):
        node = ast.Call(name="isLikelyBot", args=[])
        user_agent_arg = ast.Field(chain=["custom", "user_agent_field"])

        result = is_bot(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)
        comparison = result.args[0]
        assert isinstance(comparison, ast.CompareOperation)
        index_call = comparison.left
        assert isinstance(index_call, ast.Call)
        assert index_call.name == "multiMatchAnyIndex"
        safe_user_agent = index_call.args[0]
        assert isinstance(safe_user_agent, ast.Call)
        assert safe_user_agent.name == "ifNull"
        assert safe_user_agent.args[0] == user_agent_arg


class TestNullHandling:
    def test_build_bot_array_lookup_wraps_user_agent_in_ifnull(self):
        node = ast.Call(name="getTrafficType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_type(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)

        # Get the multiMatchAnyIndex call from the comparison
        comparison = result.args[0]
        assert isinstance(comparison, ast.CompareOperation)
        index_call = comparison.left
        assert isinstance(index_call, ast.Call)
        # First arg should be ifNull(user_agent, '')
        safe_user_agent = index_call.args[0]
        assert isinstance(safe_user_agent, ast.Call)
        assert safe_user_agent.name == "ifNull"
        assert len(safe_user_agent.args) == 2
        assert safe_user_agent.args[0] == user_agent_arg
        empty_string_arg = safe_user_agent.args[1]
        assert isinstance(empty_string_arg, ast.Constant)
        assert empty_string_arg.value == ""

    def test_is_bot_wraps_user_agent_in_ifnull(self):
        node = ast.Call(name="isLikelyBot", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = is_bot(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)
        comparison = result.args[0]
        assert isinstance(comparison, ast.CompareOperation)

        index_call = comparison.left
        assert isinstance(index_call, ast.Call)
        safe_user_agent = index_call.args[0]
        assert isinstance(safe_user_agent, ast.Call)
        assert safe_user_agent.name == "ifNull"
        assert safe_user_agent.args[0] == user_agent_arg
        empty_string_arg = safe_user_agent.args[1]
        assert isinstance(empty_string_arg, ast.Constant)
        assert empty_string_arg.value == ""


class TestBotIPClassification:
    def test_is_bot_with_ip_arg_ors_ip_match_after_ua_match(self):
        node = ast.Call(name="isLikelyBot", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])
        ip_arg = ast.Field(chain=["properties", "$ip"])

        result = is_bot(node=node, args=[user_agent_arg, ip_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "toBool"
        or_expr = result.args[0]
        assert isinstance(or_expr, ast.Or)
        assert len(or_expr.exprs) == 2
        # UA branch comes first so or() short-circuits the IP check for UA-matched rows
        ua_match = or_expr.exprs[0]
        assert isinstance(ua_match, ast.CompareOperation)
        assert isinstance(ua_match.left, ast.Call)
        assert ua_match.left.name == "multiMatchAnyIndex"
        # IP branch: one prefix-length group per collapsed prefix width, each an IN set lookup
        ip_match = or_expr.exprs[1]
        assert isinstance(ip_match, ast.Or)
        for group in ip_match.exprs:
            assert isinstance(group, ast.CompareOperation)
            assert group.op == ast.CompareOperationOp.In
            assert isinstance(group.left, ast.Call)
            assert group.left.name == "tupleElement"

    def test_is_bot_without_ip_arg_has_no_ip_branch(self):
        node = ast.Call(name="isLikelyBot", args=[])
        result = is_bot(node=node, args=[ast.Field(chain=["properties", "$user_agent"])])

        assert isinstance(result, ast.Call)
        assert isinstance(result.args[0], ast.CompareOperation)

    @parameterized.expand(
        [
            (get_traffic_type, "Regular"),
            (get_traffic_category, "regular"),
            (get_bot_type, ""),
            (get_bot_name, ""),
            (get_bot_operator, ""),
        ]
    )
    def test_lookup_builders_fall_back_to_ip_lookup_when_ua_unmatched(self, function_builder, expected_default):
        node = ast.Call(name="test", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])
        ip_arg = ast.Field(chain=["properties", "$ip"])

        result = function_builder(node=node, args=[user_agent_arg, ip_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "if"
        # The unmatched-UA branch is now the IP lookup, itself defaulting to the constant
        fallback = result.args[1]
        assert isinstance(fallback, ast.Call)
        assert fallback.name == "if"
        ip_default = fallback.args[1]
        assert isinstance(ip_default, ast.Constant)
        assert ip_default.value == expected_default
        # IP definition index is a multiIf over the per-definition range matches
        ip_index_comparison = fallback.args[0]
        assert isinstance(ip_index_comparison, ast.CompareOperation)
        assert isinstance(ip_index_comparison.left, ast.Call)
        assert ip_index_comparison.left.name == "multiIf"
        assert len(ip_index_comparison.left.args) == 2 * len(BOT_IP_DEFINITIONS) + 1


class TestBotIPDefinitionsDataStructure:
    def test_all_definitions_have_required_fields_and_valid_vocabulary(self):
        valid_types = {"AI Agent", "Bot", "Automation"}
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
        for key, ip_def in BOT_IP_DEFINITIONS.items():
            assert ip_def.name, f"IP definition {key} missing name"
            assert ip_def.operator, f"IP definition {key} missing operator"
            assert ip_def.traffic_type in valid_types, f"Invalid traffic_type for {key}: {ip_def.traffic_type}"
            assert ip_def.category in valid_categories, f"Invalid category for {key}: {ip_def.category}"
            assert ip_def.networks, f"IP definition {key} has no networks"

    def test_networks_parse_and_respect_prefix_floors(self):
        # A range wider than these floors would classify a huge slice of the internet as
        # bot traffic — refuse it here so a bad upstream refresh can't ship.
        for key, ip_def in BOT_IP_DEFINITIONS.items():
            for cidr in ip_def.networks:
                network = ipaddress.ip_network(cidr)
                floor = 16 if network.version == 4 else 32
                assert network.prefixlen >= floor, f"{key} range {cidr} wider than /{floor}"

    @parameterized.expand(
        [
            # Source IPs from the report that motivated IP-range detection: Google's mobile
            # rendering service crawling with a real Android UA (posthog#66604).
            "66.249.84.5",
            "74.125.150.10",
            "192.178.10.5",
        ]
    )
    def test_reported_google_renderer_ips_are_covered(self, ip):
        address = ipaddress.ip_address(ip)
        covered = any(
            address in ipaddress.ip_network(cidr)
            for ip_def in BOT_IP_DEFINITIONS.values()
            for cidr in ip_def.networks
            if ipaddress.ip_network(cidr).version == address.version
        )
        assert covered, f"{ip} not covered by any bot IP range"


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


# Bot-lookup macros whose builders duplicate their argument and so expand under the re-entrancy
# guard in Resolver._expand_duplicating_macro. Parameterized over so a malformed dispatch line for
# any one of them (missing guard, wrong flag reset) is caught.
DUPLICATING_MACROS = [
    "__preview_getTrafficType",
    "__preview_getTrafficCategory",
    "__preview_getBotType",
    "__preview_getBotName",
    "__preview_getBotOperator",
]


class TestMacroExpansionGuard(BaseTest):
    def _print(self, select: str) -> str:
        return prepare_and_print_ast(
            parse_select(select),
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )[0]

    @parameterized.expand(DUPLICATING_MACROS)
    def test_single_level_macro_expands(self, macro: str):
        # A non-nested call resolves and expands to the multiMatchAnyIndex lookup.
        printed = self._print(f"SELECT {macro}(toString(properties.x)) FROM events")
        assert "multiMatchAnyIndex" in printed

    @parameterized.expand(DUPLICATING_MACROS)
    def test_nested_duplicating_macro_is_rejected(self, macro: str):
        # The bot-lookup builders duplicate their argument, so a duplicating macro nested inside
        # another's expansion would blow up ~2^depth during resolution. Reject it instead.
        with pytest.raises(QueryError, match="cannot be nested inside another expanded function call"):
            self._print(f"SELECT {macro}({macro}(toString(properties.x))) FROM events")

    def test_cross_duplicating_macro_nesting_is_rejected(self):
        # Nesting two *different* duplicating macros is the same exponential vector.
        with pytest.raises(QueryError, match="cannot be nested inside another expanded function call"):
            self._print("SELECT __preview_getTrafficType(__preview_getBotName(toString(properties.x))) FROM events")

    def test_non_duplicating_macro_inside_duplicating_macro_is_allowed(self):
        # One-arg isBot does not duplicate its argument, so reaching it inside a duplicating
        # macro's expansion is bounded (not exponential) and must still resolve, not raise.
        printed = self._print("SELECT __preview_getTrafficType(toString(__preview_isBot(properties.x))) FROM events")
        assert "multiMatchAnyIndex" in printed

    def test_two_arg_is_bot_expands_ip_ranges(self):
        printed = self._print(
            "SELECT isLikelyBot(toString(properties.$user_agent), toString(properties.$ip)) FROM events"
        )
        assert "multiMatchAnyIndex" in printed
        assert "IPv6CIDRToRange" in printed

    def test_two_arg_is_bot_nested_is_rejected(self):
        # The two-arg form duplicates its IP argument across the per-prefix-length range
        # checks, so nesting it is the same exponential vector as the lookup macros.
        with pytest.raises(QueryError, match="cannot be nested inside another expanded function call"):
            self._print(
                "SELECT isLikelyBot(toString(isLikelyBot(properties.x, toString(properties.$ip))), toString(properties.$ip)) FROM events"
            )

    def test_matches_action_with_macro_property_still_resolves(self):
        # matchesAction expands a user-defined action, whose hogql property filters re-parse
        # arbitrary user HogQL. A guarded macro referenced there must still expand — the guard
        # must not fire across matchesAction's (bounded) action expansion.
        action = Action.objects.create(
            team=self.team,
            steps_json=[
                {
                    "event": "$pageview",
                    "properties": [
                        {"type": "hogql", "key": "__preview_getTrafficType(properties.$user_agent) = 'Bot'"}
                    ],
                }
            ],
        )
        printed = self._print(f"SELECT matchesAction({action.pk}) FROM events")
        assert "multiMatchAnyIndex" in printed
