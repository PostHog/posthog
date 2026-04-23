from dataclasses import dataclass

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.functions.llm_complete import LLM_COMPLETE_FUNCTION_NAME, extract_llm_complete_args
from posthog.hogql.visitor import TraversingVisitor


@dataclass
class LlmCompletionSpec:
    """Describes one column in the outer SELECT that needs post-query LLM substitution."""

    column_index: int
    column_alias: str
    model: str
    system_prompt: str | None


def rewrite_llm_completions(node: ast.AST, context: HogQLContext) -> None:
    """Rewrite top-level `__preview_llm_complete(...)` calls in the outer SELECT.

    Each call is replaced with its prompt expression so ClickHouse renders the prompt
    string per row. A spec is appended to ``context.llm_completions`` that the executor
    uses to replace the rendered prompts with LLM completions after the query returns.

    For v1, calls are only allowed as the direct expression of an outer SELECT item
    (optionally wrapped in an Alias). Any other position raises QueryError.
    """
    outer = _find_outer_select(node)
    if outer is None:
        _ForbidLlmComplete().visit(node)
        return

    allowed_call_ids: set[int] = set()
    for idx, column in enumerate(outer.select):
        call = _direct_llm_call(column)
        if call is None:
            continue
        allowed_call_ids.add(id(call))
        model, prompt_expr, system_prompt = extract_llm_complete_args(call)
        alias = column.alias if isinstance(column, ast.Alias) else f"__llm_complete_{idx}"
        outer.select[idx] = ast.Alias(alias=alias, expr=prompt_expr)
        context.llm_completions.append(
            LlmCompletionSpec(
                column_index=idx,
                column_alias=alias,
                model=model,
                system_prompt=system_prompt,
            )
        )

    _ForbidLlmComplete(allowed_call_ids=allowed_call_ids).visit(outer)


def _find_outer_select(node: ast.AST) -> ast.SelectQuery | None:
    if isinstance(node, ast.SelectQuery):
        return node
    if isinstance(node, ast.SelectSetQuery):
        # For UNIONs we only rewrite the initial SELECT's columns — its aliases drive the result schema.
        return _find_outer_select(node.initial_select_query)
    return None


def _direct_llm_call(column: ast.Expr) -> ast.Call | None:
    inner = column.expr if isinstance(column, ast.Alias) else column
    if isinstance(inner, ast.Call) and inner.name == LLM_COMPLETE_FUNCTION_NAME:
        return inner
    return None


class _ForbidLlmComplete(TraversingVisitor):
    """Raises if it encounters __preview_llm_complete anywhere the rewrite didn't own."""

    def __init__(self, allowed_call_ids: set[int] | None = None) -> None:
        super().__init__()
        self._allowed = allowed_call_ids or set()

    def visit_call(self, node: ast.Call) -> None:
        if node.name == LLM_COMPLETE_FUNCTION_NAME and id(node) not in self._allowed:
            raise QueryError(
                f"{LLM_COMPLETE_FUNCTION_NAME}() may only be used as a top-level column "
                "in the outer SELECT (optionally aliased). Nested or non-SELECT positions "
                "are not supported."
            )
        super().visit_call(node)
