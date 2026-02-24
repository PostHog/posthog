import pytest

from posthog.hogql import ast
from posthog.hogql.functions.traffic_type import get_bot_type, get_traffic_category, get_traffic_type, is_bot


class TestTrafficTypeFunctions:
    """Test the HogQL traffic type functions."""

    def test_get_traffic_type_returns_multiif(self):
        node = ast.Call(name="__preview_getTrafficType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_type(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "multiIf"
        # Should have 17 args: 8 conditions * 2 + 1 default
        assert len(result.args) == 17

    def test_get_traffic_type_returns_expected_values(self):
        node = ast.Call(name="__preview_getTrafficType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_type(node=node, args=[user_agent_arg])

        # Extract all constant values
        return_values = [arg.value for arg in result.args if isinstance(arg, ast.Constant)]

        assert "AI Agent" in return_values
        assert "Bot" in return_values
        assert "Automation" in return_values
        assert "Regular" in return_values

    def test_get_traffic_category_returns_multiif(self):
        node = ast.Call(name="__preview_getTrafficCategory", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_category(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "multiIf"
        # Should have 17 args: 8 conditions * 2 + 1 default
        assert len(result.args) == 17

    def test_get_traffic_category_returns_expected_values(self):
        node = ast.Call(name="__preview_getTrafficCategory", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_category(node=node, args=[user_agent_arg])

        # Extract all constant values
        return_values = [arg.value for arg in result.args if isinstance(arg, ast.Constant)]

        assert "llm_crawler" in return_values
        assert "search_crawler" in return_values
        assert "http_client" in return_values
        assert "regular" in return_values


class TestIsBotFunction:
    """Test the __preview_isBot function."""

    def test_is_bot_returns_or_expression(self):
        node = ast.Call(name="__preview_isBot", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = is_bot(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Or)
        # Should have 8 match conditions (all bot patterns + empty UA)
        assert len(result.exprs) == 8

    def test_is_bot_uses_match_calls(self):
        node = ast.Call(name="__preview_isBot", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = is_bot(node=node, args=[user_agent_arg])

        for expr in result.exprs:
            assert isinstance(expr, ast.Call)
            assert expr.name == "match"


class TestGetBotTypeFunction:
    """Test the __preview_getBotType function."""

    def test_get_bot_type_returns_multiif(self):
        node = ast.Call(name="__preview_getBotType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_bot_type(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "multiIf"
        # Should have 17 args: 8 conditions * 2 + 1 default
        assert len(result.args) == 17

    def test_get_bot_type_returns_expected_values(self):
        node = ast.Call(name="__preview_getBotType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_bot_type(node=node, args=[user_agent_arg])

        # Extract all constant values
        return_values = [arg.value for arg in result.args if isinstance(arg, ast.Constant)]

        assert "llm_crawler" in return_values
        assert "search_crawler" in return_values
        assert "seo_crawler" in return_values
        assert "social_crawler" in return_values
        assert "monitoring" in return_values
        assert "http_client" in return_values
        assert "headless_browser" in return_values
        assert "no_user_agent" in return_values
        # Regular traffic returns empty string
        assert "" in return_values


class TestTrafficTypeFunctionPatterns:
    """Test that patterns are applied correctly to user agent expressions."""

    @pytest.mark.parametrize(
        "function_builder,expected_name",
        [
            (get_traffic_type, "multiIf"),
            (get_traffic_category, "multiIf"),
            (get_bot_type, "multiIf"),
        ],
    )
    def test_functions_preserve_user_agent_expression(self, function_builder, expected_name):
        node = ast.Call(name="test", args=[])
        user_agent_arg = ast.Field(chain=["custom", "user_agent_field"])

        result = function_builder(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == expected_name
        # First condition should use our custom user agent field
        first_match = result.args[0]
        assert isinstance(first_match, ast.Call)
        assert first_match.name == "match"
        assert first_match.args[0] == user_agent_arg

    def test_is_bot_preserves_user_agent_expression(self):
        node = ast.Call(name="__preview_isBot", args=[])
        user_agent_arg = ast.Field(chain=["custom", "user_agent_field"])

        result = is_bot(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Or)
        # All match calls should use our custom user agent field
        for expr in result.exprs:
            assert isinstance(expr, ast.Call)
            assert expr.args[0] == user_agent_arg
