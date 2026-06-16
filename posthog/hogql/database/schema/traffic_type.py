from typing import Optional

from posthog.hogql import ast
from posthog.hogql.database.models import ExpressionField


def user_agent_expr(properties_path: Optional[list[str]] = None) -> ast.Expr:
    if not properties_path:
        properties_path = ["properties"]
    return ast.Call(
        name="coalesce",
        args=[
            ast.Call(
                name="nullIf",
                args=[
                    ast.Field(chain=[*properties_path, "$raw_user_agent"]),
                    ast.Constant(value=""),
                ],
            ),
            ast.Field(chain=[*properties_path, "$user_agent"]),
        ],
    )


# These one-node calls are expanded to the classification SQL by the printer's visit_call (see
# functions.traffic_type.TRAFFIC_TYPE_PRINTER_BUILDERS), so it only materializes for queries that use it.
def create_is_bot_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name, expr=ast.Call(name="__preview_isBot", args=[user_agent_expr(properties_path)]), isolate_scope=True
    )


def create_traffic_type_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=ast.Call(name="__preview_getTrafficType", args=[user_agent_expr(properties_path)]),
        isolate_scope=True,
    )


def create_traffic_category_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=ast.Call(name="__preview_getTrafficCategory", args=[user_agent_expr(properties_path)]),
        isolate_scope=True,
    )


def create_bot_name_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=ast.Call(name="__preview_getBotName", args=[user_agent_expr(properties_path)]),
        isolate_scope=True,
    )


def create_bot_operator_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=ast.Call(name="__preview_getBotOperator", args=[user_agent_expr(properties_path)]),
        isolate_scope=True,
    )
