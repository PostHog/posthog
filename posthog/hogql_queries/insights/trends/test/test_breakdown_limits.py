from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.constants import BREAKDOWN_VALUE_MAX_LENGTH

from posthog.hogql_queries.insights.trends.breakdown import Breakdown


class TestBreakdownValueTruncation(BaseTest):
    def test_replace_null_values_transform_includes_left_truncation(self):
        node = ast.Field(chain=["properties", "$browser"])
        result = Breakdown.get_replace_null_values_transform(node)

        # The outermost call is ifNull(nullIf(left(toString(...), N), ''), nil)
        assert isinstance(result, ast.Call)
        assert result.name == "ifNull"
        null_if_call = result.args[0]
        assert isinstance(null_if_call, ast.Call)
        assert null_if_call.name == "nullIf"
        left_call = null_if_call.args[0]
        assert isinstance(left_call, ast.Call)
        assert left_call.name == "left"
        to_string_call = left_call.args[0]
        assert isinstance(to_string_call, ast.Call)
        assert to_string_call.name == "toString"
        max_length = left_call.args[1]
        assert isinstance(max_length, ast.Constant)
        assert max_length.value == BREAKDOWN_VALUE_MAX_LENGTH
