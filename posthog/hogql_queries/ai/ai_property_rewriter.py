"""AST rewriter that transforms `properties.$ai_*` field references to dedicated `ai_events` column names.

Follows the `ExprTransformer` / `CloningVisitor` pattern from
`posthog/hogql/transforms/preaggregated_table_transformation.py`.
"""

from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor

# Mapping from AI property names to their dedicated ai_events column names.
# Properties not in this mapping remain as JSONExtract on the `properties` column.
AI_PROPERTY_TO_COLUMN: dict[str, str] = {
    # Trace structure
    "$ai_trace_id": "trace_id",
    "$ai_session_id": "session_id",
    "$ai_parent_id": "parent_id",
    "$ai_span_id": "span_id",
    "$ai_span_type": "span_type",
    "$ai_generation_id": "generation_id",
    "$ai_experiment_id": "experiment_id",
    # Names
    "$ai_span_name": "span_name",
    "$ai_trace_name": "trace_name",
    "$ai_prompt_name": "prompt_name",
    # Model info
    "$ai_model": "model",
    "$ai_provider": "provider",
    "$ai_framework": "framework",
    # Token counts
    "$ai_total_tokens": "total_tokens",
    "$ai_input_tokens": "input_tokens",
    "$ai_output_tokens": "output_tokens",
    "$ai_text_input_tokens": "text_input_tokens",
    "$ai_text_output_tokens": "text_output_tokens",
    "$ai_image_input_tokens": "image_input_tokens",
    "$ai_image_output_tokens": "image_output_tokens",
    "$ai_audio_input_tokens": "audio_input_tokens",
    "$ai_audio_output_tokens": "audio_output_tokens",
    "$ai_video_input_tokens": "video_input_tokens",
    "$ai_video_output_tokens": "video_output_tokens",
    "$ai_reasoning_tokens": "reasoning_tokens",
    "$ai_cache_read_input_tokens": "cache_read_input_tokens",
    "$ai_cache_creation_input_tokens": "cache_creation_input_tokens",
    "$ai_web_search_count": "web_search_count",
    # Costs
    "$ai_input_cost_usd": "input_cost_usd",
    "$ai_output_cost_usd": "output_cost_usd",
    "$ai_total_cost_usd": "total_cost_usd",
    "$ai_request_cost_usd": "request_cost_usd",
    "$ai_web_search_cost_usd": "web_search_cost_usd",
    "$ai_audio_cost_usd": "audio_cost_usd",
    "$ai_image_cost_usd": "image_cost_usd",
    "$ai_video_cost_usd": "video_cost_usd",
    # Timing
    "$ai_latency": "latency",
    "$ai_time_to_first_token": "time_to_first_token",
    # Errors
    "$ai_is_error": "is_error",
    "$ai_error": "error",
    "$ai_error_type": "error_type",
    "$ai_error_normalized": "error_normalized",
    # Heavy columns
    "$ai_input": "input",
    "$ai_output": "output",
    "$ai_output_choices": "output_choices",
    "$ai_input_state": "input_state",
    "$ai_output_state": "output_state",
    "$ai_tools": "tools",
}

_BOOLEAN_PROPERTIES: frozenset[str] = frozenset({"$ai_is_error"})

# Values that map to UInt8 1 (truthy) for boolean AI property columns
_TRUTHY_VALUES: frozenset[str | bool | int] = frozenset({"true", True, "1"})
# Values that map to UInt8 0 (falsy) for boolean AI property columns
_FALSY_VALUES: frozenset[str | bool | int] = frozenset({"false", False, "0", ""})


def _rewrite_property_field(chain: list[str | int]) -> tuple[list[str | int], str | None] | None:
    """If chain matches `properties.$ai_*`, return (rewritten_chain, property_name).

    Handles patterns:
      - ["properties", "$ai_foo"]          → (["column_name"], "$ai_foo")
      - ["events", "properties", "$ai_foo"] → (["events", "column_name"], "$ai_foo")

    Returns None if the field is not a rewritable AI property.
    """
    if len(chain) >= 2 and chain[-2] == "properties":
        prop_name = chain[-1]
        if isinstance(prop_name, str) and prop_name in AI_PROPERTY_TO_COLUMN:
            prefix = list(chain[:-2])
            return [*prefix, AI_PROPERTY_TO_COLUMN[prop_name]], prop_name
    return None


def _is_boolean_property_field(node: ast.Expr) -> bool:
    """Check if an expression is a Field referencing a boolean AI property."""
    if not isinstance(node, ast.Field):
        return False
    result = _rewrite_property_field(node.chain)
    return result is not None and result[1] in _BOOLEAN_PROPERTIES


def _normalize_boolean_constant(value: object) -> ast.Constant | None:
    """Convert a truthy/falsy value to a UInt8-compatible constant (1 or 0)."""
    if value in _TRUTHY_VALUES:
        return ast.Constant(value=1)
    if value in _FALSY_VALUES:
        return ast.Constant(value=0)
    return None


class AiPropertyRewriter(CloningVisitor):
    """Rewrites `properties.$ai_*` field references to dedicated ai_events column references.

    Boolean properties like `$ai_is_error` map to native UInt8 columns. When a boolean
    property appears in a comparison (e.g. `properties.$ai_is_error = 'true'` or `= True`),
    the constant is normalized to UInt8 (1/0) to match the column type. This handles both
    hardcoded HogQL strings (value='true') and property_to_expr output (value=True).
    """

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.Expr:
        # Intercept comparisons involving boolean AI properties before field-level
        # rewriting, so we can normalize the constant side to UInt8.
        left_is_bool = _is_boolean_property_field(node.left)
        right_is_bool = _is_boolean_property_field(node.right)

        if left_is_bool and isinstance(node.right, ast.Constant):
            new_const = _normalize_boolean_constant(node.right.value)
            if new_const is not None:
                return ast.CompareOperation(
                    op=node.op,
                    left=self.visit(node.left),
                    right=new_const,
                )

        if right_is_bool and isinstance(node.left, ast.Constant):
            new_const = _normalize_boolean_constant(node.left.value)
            if new_const is not None:
                return ast.CompareOperation(
                    op=node.op,
                    left=new_const,
                    right=self.visit(node.right),
                )

        return super().visit_compare_operation(node)

    def visit_field(self, node: ast.Field) -> ast.Expr:
        result = _rewrite_property_field(node.chain)
        if result is not None:
            chain, _prop_name = result
            return ast.Field(chain=chain)
        return super().visit_field(node)


def rewrite_expr_for_ai_events_table(expr: ast.Expr) -> ast.Expr:
    """Rewrite property references in a standalone expression to use ai_events dedicated columns."""
    return AiPropertyRewriter().visit(expr)
