from posthog.hogql import ast
from posthog.hogql.functions.traffic_type import get_traffic_category, get_traffic_type


class TestTrafficTypeFunctions:
    """Test the HogQL traffic type functions."""

    def test_get_traffic_type_returns_multiif(self):
        node = ast.Call(name="getTrafficType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_type(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "multiIf"
        # Should have 17 args: 8 conditions * 2 + 1 default
        assert len(result.args) == 17

    def test_get_traffic_type_returns_expected_values(self):
        node = ast.Call(name="getTrafficType", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_type(node=node, args=[user_agent_arg])

        # Extract all constant values
        return_values = [arg.value for arg in result.args if isinstance(arg, ast.Constant)]

        assert "AI Agent" in return_values
        assert "Bot" in return_values
        assert "Automation" in return_values
        assert "Human" in return_values

    def test_get_traffic_category_returns_multiif(self):
        node = ast.Call(name="getTrafficCategory", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_category(node=node, args=[user_agent_arg])

        assert isinstance(result, ast.Call)
        assert result.name == "multiIf"
        # Should have 17 args: 8 conditions * 2 + 1 default
        assert len(result.args) == 17

    def test_get_traffic_category_returns_expected_values(self):
        node = ast.Call(name="getTrafficCategory", args=[])
        user_agent_arg = ast.Field(chain=["properties", "$user_agent"])

        result = get_traffic_category(node=node, args=[user_agent_arg])

        # Extract all constant values
        return_values = [arg.value for arg in result.args if isinstance(arg, ast.Constant)]

        assert "llm_crawler" in return_values
        assert "search_crawler" in return_values
        assert "http_client" in return_values
        assert "human" in return_values
