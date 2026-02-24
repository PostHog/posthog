import pytest

from posthog.hogql import ast
from posthog.hogql.functions.traffic_type import (
    BOT_DEFINITIONS,
    get_bot_name,
    get_bot_type,
    get_traffic_category,
    get_traffic_type,
    is_bot,
)


class TestTrafficTypeFunctions:
    def test_get_traffic_type_returns_multiif(self):
        node = ast.Call(name="__preview_getTrafficType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_type(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "multiIf"
        # Should have: (len(BOT_DEFINITIONS) conditions * 2) + (empty UA condition * 2) + 1 default
        expected_args = len(BOT_DEFINITIONS) * 2 + 2 + 1
        assert len(result.args) == expected_args

    def test_get_traffic_type_returns_expected_values(self):
        node = ast.Call(name="__preview_getTrafficType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_type(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)

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
        # Should have: (len(BOT_DEFINITIONS) conditions * 2) + (empty UA condition * 2) + 1 default
        expected_args = len(BOT_DEFINITIONS) * 2 + 2 + 1
        assert len(result.args) == expected_args

    def test_get_traffic_category_returns_expected_values(self):
        node = ast.Call(name="__preview_getTrafficCategory", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_category(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)

        return_values = [arg.value for arg in result.args if isinstance(arg, ast.Constant)]

        assert "llm_crawler" in return_values
        assert "search_crawler" in return_values
        assert "http_client" in return_values
        assert "regular" in return_values


class TestIsBotFunction:
    def test_is_bot_returns_multiMatchAny(self):
        node = ast.Call(name="__preview_isBot", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = is_bot(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "multiMatchAny"
        assert len(result.args) == 2

    def test_is_bot_has_correct_patterns(self):
        node = ast.Call(name="__preview_isBot", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = is_bot(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)

        # First arg is the user agent expression
        assert result.args[0] == user_agent_arg

        # Second arg is the patterns array
        patterns_array = result.args[1]
        assert isinstance(patterns_array, ast.Array)
        # Should have len(BOT_DEFINITIONS) + 1 (empty UA) patterns
        assert len(patterns_array.exprs) == len(BOT_DEFINITIONS) + 1


class TestGetBotTypeFunction:
    def test_get_bot_type_returns_multiif(self):
        node = ast.Call(name="__preview_getBotType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_bot_type(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "multiIf"
        # Should have: (len(BOT_DEFINITIONS) conditions * 2) + (empty UA condition * 2) + 1 default
        expected_args = len(BOT_DEFINITIONS) * 2 + 2 + 1
        assert len(result.args) == expected_args

    def test_get_bot_type_returns_expected_values(self):
        node = ast.Call(name="__preview_getBotType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_bot_type(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)

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


class TestGetBotNameFunction:
    def test_get_bot_name_returns_multiif(self):
        node = ast.Call(name="__preview_getBotName", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_bot_name(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "multiIf"
        # Should have: (len(BOT_DEFINITIONS) conditions * 2) + (empty UA condition * 2) + 1 default
        expected_args = len(BOT_DEFINITIONS) * 2 + 2 + 1
        assert len(result.args) == expected_args

    def test_get_bot_name_returns_expected_values(self):
        node = ast.Call(name="__preview_getBotName", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_bot_name(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)

        return_values = [arg.value for arg in result.args if isinstance(arg, ast.Constant)]

        # Check some expected bot names
        assert "Googlebot" in return_values
        assert "ChatGPT" in return_values
        assert "Claude" in return_values
        assert "curl" in return_values
        # Regular traffic returns empty string
        assert "" in return_values

    def test_get_bot_name_preserves_user_agent_expression(self):
        node = ast.Call(name="test", args=[])
        user_agent_arg = ast.Field(chain=["custom", "user_agent_field"])

        result = get_bot_name(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "multiIf"
        # First condition should use our custom user agent field
        first_match = result.args[0]
        assert isinstance(first_match, ast.Call)
        assert first_match.name == "match"
        assert first_match.args[0] == user_agent_arg


class TestTrafficTypeFunctionPatterns:
    @pytest.mark.parametrize(
        "function_builder,expected_name",
        [
            (get_traffic_type, "multiIf"),
            (get_traffic_category, "multiIf"),
            (get_bot_type, "multiIf"),
            (get_bot_name, "multiIf"),
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
        assert isinstance(result, ast.Call)
        assert result.name == "multiMatchAny"
        assert result.args[0] == user_agent_arg


class TestBotDefinitionsDataStructure:
    def test_all_bot_definitions_have_required_fields(self):
        for pattern, bot_def in BOT_DEFINITIONS.items():
            assert bot_def.name, f"Bot definition for {pattern} missing name"
            assert bot_def.category, f"Bot definition for {pattern} missing category"
            assert bot_def.traffic_type, f"Bot definition for {pattern} missing traffic_type"

    def test_traffic_types_are_valid(self):
        valid_types = {"AI Agent", "Bot", "Automation"}
        for pattern, bot_def in BOT_DEFINITIONS.items():
            assert bot_def.traffic_type in valid_types, f"Invalid traffic_type for {pattern}: {bot_def.traffic_type}"

    def test_categories_are_valid(self):
        valid_categories = {
            "llm_crawler",
            "search_crawler",
            "seo_crawler",
            "social_crawler",
            "monitoring",
            "http_client",
            "headless_browser",
        }
        for pattern, bot_def in BOT_DEFINITIONS.items():
            assert bot_def.category in valid_categories, f"Invalid category for {pattern}: {bot_def.category}"
