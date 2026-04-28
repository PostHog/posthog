from typing import Optional

from posthog.hogql import ast
from posthog.hogql.database.models import ExpressionField
from posthog.hogql.functions.traffic_type import (
    get_bot_name,
    get_bot_operator,
    get_traffic_category,
    get_traffic_type,
    is_bot,
)


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


def _dummy_call(name: str = "__placeholder") -> ast.Call:
    return ast.Call(name=name, args=[])


def create_is_bot_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=is_bot(node=_dummy_call(name), args=[user_agent_expr(properties_path)]),
        isolate_scope=True,
    )


def create_traffic_type_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=get_traffic_type(node=_dummy_call(name), args=[user_agent_expr(properties_path)]),
        isolate_scope=True,
    )


def create_traffic_category_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=get_traffic_category(node=_dummy_call(name), args=[user_agent_expr(properties_path)]),
        isolate_scope=True,
    )


def create_bot_name_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=get_bot_name(node=_dummy_call(name), args=[user_agent_expr(properties_path)]),
        isolate_scope=True,
    )


def create_bot_operator_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=get_bot_operator(node=_dummy_call(name), args=[user_agent_expr(properties_path)]),
        isolate_scope=True,
    )


def log_user_agent_expr() -> ast.Expr:
    """Resolve user agent from log attributes, checking OTEL and PostHog conventions.

    Goes through `attributes_map_str` (raw stored Map column with `__str`-suffixed keys)
    rather than the `attributes` alias. The alias strips the `__str` suffix and is exposed
    as a JSON-typed HogQL field for the legacy query-runner path; for our purposes we want
    direct Map subscript access against the underlying column.
    """
    return ast.Call(
        name="coalesce",
        args=[
            ast.Call(
                name="nullIf",
                args=[ast.Field(chain=["attributes_map_str", "http.user_agent__str"]), ast.Constant(value="")],
            ),
            ast.Call(
                name="nullIf",
                args=[ast.Field(chain=["attributes_map_str", "user_agent.original__str"]), ast.Constant(value="")],
            ),
            ast.Call(
                name="nullIf",
                args=[ast.Field(chain=["attributes_map_str", "$raw_user_agent__str"]), ast.Constant(value="")],
            ),
            ast.Field(chain=["attributes_map_str", "$user_agent__str"]),
        ],
    )


def create_log_is_bot_field(name: str) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=is_bot(node=_dummy_call(name), args=[log_user_agent_expr()]),
        isolate_scope=True,
    )


def create_log_traffic_type_field(name: str) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=get_traffic_type(node=_dummy_call(name), args=[log_user_agent_expr()]),
        isolate_scope=True,
    )


def create_log_traffic_category_field(name: str) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=get_traffic_category(node=_dummy_call(name), args=[log_user_agent_expr()]),
        isolate_scope=True,
    )


def create_log_bot_name_field(name: str) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=get_bot_name(node=_dummy_call(name), args=[log_user_agent_expr()]),
        isolate_scope=True,
    )


def create_log_bot_operator_field(name: str) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=get_bot_operator(node=_dummy_call(name), args=[log_user_agent_expr()]),
        isolate_scope=True,
    )
