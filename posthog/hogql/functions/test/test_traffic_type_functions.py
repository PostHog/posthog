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
    def test_get_traffic_type_returns_if_with_array_lookup(self):
        node = ast.Call(name="__preview_getTrafficType", args=[])
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
        node = ast.Call(name="__preview_getTrafficType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_type(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)

        # Check the comparison contains multiMatchAnyIndex
        comparison = result.args[0]
        assert isinstance(comparison, ast.CompareOperation)
        assert isinstance(comparison.left, ast.Call)
        assert comparison.left.name == "multiMatchAnyIndex"

    def test_get_traffic_type_has_correct_patterns_and_labels(self):
        node = ast.Call(name="__preview_getTrafficType", args=[])
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
        node = ast.Call(name="__preview_getTrafficCategory", args=[])
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
        node = ast.Call(name="__preview_getTrafficCategory", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_category(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)

        # Get labels from the array access
        array_access = result.args[2]
        assert isinstance(array_access, ast.ArrayAccess)
        labels_array = array_access.array
        assert isinstance(labels_array, ast.Array)

        label_values = [expr.value for expr in labels_array.exprs if isinstance(expr, ast.Constant)]

        assert "llm_crawler" in label_values
        assert "search_crawler" in label_values
        assert "http_client" in label_values
        assert "no_user_agent" in label_values  # For empty UA


class TestIsBotFunction:
    def test_is_bot_returns_or_expression(self):
        node = ast.Call(name="__preview_isBot", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = is_bot(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Or)
        # Should have len(BOT_DEFINITIONS) + 1 (empty UA) match conditions
        assert len(result.exprs) == len(BOT_DEFINITIONS) + 1

    def test_is_bot_uses_match_calls(self):
        node = ast.Call(name="__preview_isBot", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = is_bot(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Or)

        for expr in result.exprs:
            assert isinstance(expr, ast.Call)
            assert expr.name == "match"


class TestGetBotTypeFunction:
    def test_get_bot_type_returns_if_with_array_lookup(self):
        node = ast.Call(name="__preview_getBotType", args=[])
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
        node = ast.Call(name="__preview_getBotType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_bot_type(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Call)

        # Get labels from the array access
        array_access = result.args[2]
        assert isinstance(array_access, ast.ArrayAccess)
        labels_array = array_access.array
        assert isinstance(labels_array, ast.Array)

        label_values = [expr.value for expr in labels_array.exprs if isinstance(expr, ast.Constant)]

        assert "llm_crawler" in label_values
        assert "search_crawler" in label_values
        assert "seo_crawler" in label_values
        assert "social_crawler" in label_values
        assert "monitoring" in label_values
        assert "http_client" in label_values
        assert "headless_browser" in label_values
        assert "no_user_agent" in label_values


class TestGetBotNameFunction:
    def test_get_bot_name_returns_if_with_array_lookup(self):
        node = ast.Call(name="__preview_getBotName", args=[])
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
        node = ast.Call(name="__preview_getBotName", args=[])
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
        node = ast.Call(name="__preview_isBot", args=[])
        user_agent_arg = ast.Field(chain=["custom", "user_agent_field"])

        result = is_bot(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Or)

        for expr in result.exprs:
            assert isinstance(expr, ast.Call)
            # User agent is wrapped in ifNull(user_agent, '')
            safe_user_agent = expr.args[0]
            assert isinstance(safe_user_agent, ast.Call)
            assert safe_user_agent.name == "ifNull"
            assert safe_user_agent.args[0] == user_agent_arg


class TestNullHandling:
    def test_build_bot_array_lookup_wraps_user_agent_in_ifnull(self):
        node = ast.Call(name="__preview_getTrafficType", args=[])
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
        node = ast.Call(name="__preview_isBot", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = is_bot(node=node, args=[user_agent_arg])
        assert isinstance(result, ast.Or)

        # All match calls should use ifNull(user_agent, '')
        for match_call in result.exprs:
            assert isinstance(match_call, ast.Call)
            safe_user_agent = match_call.args[0]
            assert isinstance(safe_user_agent, ast.Call)
            assert safe_user_agent.name == "ifNull"
            assert safe_user_agent.args[0] == user_agent_arg
            empty_string_arg = safe_user_agent.args[1]
            assert isinstance(empty_string_arg, ast.Constant)
            assert empty_string_arg.value == ""


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
