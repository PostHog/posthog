from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.ai.ai_property_rewriter import AiPropertyRewriter, _rewrite_property_field


class TestRewritePropertyField:
    def test_simple_ai_property(self):
        result = _rewrite_property_field(["properties", "$ai_trace_id"])
        assert result is not None
        chain, prop_name = result
        assert chain == ["trace_id"]
        assert prop_name == "$ai_trace_id"

    def test_table_prefixed_ai_property(self):
        result = _rewrite_property_field(["events", "properties", "$ai_model"])
        assert result is not None
        chain, prop_name = result
        assert chain == ["events", "model"]
        assert prop_name == "$ai_model"

    def test_non_ai_property_returns_none(self):
        assert _rewrite_property_field(["properties", "$browser"]) is None

    def test_short_chain_returns_none(self):
        assert _rewrite_property_field(["$ai_trace_id"]) is None

    def test_non_properties_parent_returns_none(self):
        assert _rewrite_property_field(["other", "$ai_trace_id"]) is None


class TestAiPropertyRewriter:
    def test_rewrites_ai_property_field(self):
        node = ast.Field(chain=["properties", "$ai_trace_id"])
        rewriter = AiPropertyRewriter()
        result = rewriter.visit(node)
        assert isinstance(result, ast.Field)
        assert result.chain == ["trace_id"]

    def test_boolean_property_wrapped_in_if(self):
        node = ast.Field(chain=["properties", "$ai_is_error"])
        rewriter = AiPropertyRewriter()
        result = rewriter.visit(node)
        assert isinstance(result, ast.Call)
        assert result.name == "if"
        assert len(result.args) == 3
        assert isinstance(result.args[0], ast.Field)
        assert result.args[0].chain == ["is_error"]
        assert isinstance(result.args[1], ast.Constant)
        assert result.args[1].value == "true"
        assert isinstance(result.args[2], ast.Constant)
        assert result.args[2].value == ""

    def test_non_ai_property_unchanged(self):
        node = ast.Field(chain=["properties", "$browser"])
        rewriter = AiPropertyRewriter()
        result = rewriter.visit(node)
        assert isinstance(result, ast.Field)
        assert result.chain == ["properties", "$browser"]

    def test_rewrite_with_table_prefix(self):
        node = ast.Field(chain=["events", "properties", "$ai_model"])
        rewriter = AiPropertyRewriter()
        result = rewriter.visit(node)
        assert isinstance(result, ast.Field)
        assert result.chain == ["events", "model"]

    def test_full_query_ast_roundtrip(self):
        query = parse_select("SELECT properties.$ai_trace_id, properties.$browser FROM events")
        rewriter = AiPropertyRewriter()
        rewritten = rewriter.visit(query)
        # First select: properties.$ai_trace_id → trace_id field
        assert isinstance(rewritten.select[0], ast.Field)
        assert rewritten.select[0].chain == ["trace_id"]
        # Second select: properties.$browser left unchanged
        assert isinstance(rewritten.select[1], ast.Field)
        assert rewritten.select[1].chain == ["properties", "$browser"]
