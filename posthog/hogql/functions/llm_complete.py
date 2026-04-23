from posthog.hogql import ast
from posthog.hogql.errors import QueryError


LLM_COMPLETE_FUNCTION_NAME = "__preview_llm_complete"


def extract_llm_complete_args(node: ast.Call) -> tuple[str, ast.Expr, str | None]:
    """Validate a __preview_llm_complete(...) call and return (model, prompt_expr, system_prompt).

    The model and optional system arguments must be string literals; the prompt is an
    arbitrary HogQL expression that ClickHouse will evaluate per row.
    """
    if node.name != LLM_COMPLETE_FUNCTION_NAME:
        raise QueryError(f"Expected {LLM_COMPLETE_FUNCTION_NAME} call, got {node.name!r}")
    if len(node.args) < 2 or len(node.args) > 3:
        raise QueryError(f"{LLM_COMPLETE_FUNCTION_NAME}() takes 2 or 3 arguments, got {len(node.args)}")

    model_arg, prompt_arg, *rest = node.args

    if not isinstance(model_arg, ast.Constant) or not isinstance(model_arg.value, str) or not model_arg.value:
        raise QueryError(f"{LLM_COMPLETE_FUNCTION_NAME}(): model (1st arg) must be a non-empty string literal")

    system_prompt: str | None = None
    if rest:
        system_arg = rest[0]
        if not isinstance(system_arg, ast.Constant) or not isinstance(system_arg.value, str):
            raise QueryError(f"{LLM_COMPLETE_FUNCTION_NAME}(): system prompt (3rd arg) must be a string literal")
        system_prompt = system_arg.value

    return model_arg.value, prompt_arg, system_prompt
