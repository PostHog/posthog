from typing import Optional

from posthog.hogql import ast
from posthog.hogql.database.models import ExpressionField


def user_agent_expr(properties_path: Optional[list[str]] = None) -> ast.Expr:
    # Intentionally no fallback to properties.$user_agent: that property has no materialized
    # column, so referencing it forces a full properties-blob read on every query using these
    # fields, and it only carries a value on a tiny fraction of events (SDKs that send it
    # without $raw_user_agent). Those events classify via the empty-UA path instead, same as
    # SDKs that send no user agent at all.
    if not properties_path:
        properties_path = ["properties"]
    return ast.Field(chain=[*properties_path, "$raw_user_agent"])


def client_ip_expr(properties_path: Optional[list[str]] = None) -> ast.Expr:
    if not properties_path:
        properties_path = ["properties"]
    return ast.Field(chain=[*properties_path, "$ip"])


def _classification_args(properties_path: Optional[list[str]] = None) -> list[ast.Expr]:
    return [user_agent_expr(properties_path), client_ip_expr(properties_path)]


def client_ip_expr(properties_path: Optional[list[str]] = None) -> ast.Expr:
    if not properties_path:
        properties_path = ["properties"]
    return ast.Field(chain=[*properties_path, "$ip"])


def _classification_args(properties_path: Optional[list[str]] = None) -> list[ast.Expr]:
    return [user_agent_expr(properties_path), client_ip_expr(properties_path)]


# These one-node calls are expanded to the classification SQL in the resolver (see Resolver.visit_call),
# so the big expression only materializes for queries that select the field.
def create_is_bot_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name, expr=ast.Call(name="isLikelyBot", args=_classification_args(properties_path)), isolate_scope=True
    )


def create_traffic_type_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=ast.Call(name="getTrafficType", args=_classification_args(properties_path)),
        isolate_scope=True,
    )


def create_traffic_category_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=ast.Call(name="getTrafficCategory", args=_classification_args(properties_path)),
        isolate_scope=True,
    )


def create_bot_name_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=ast.Call(name="getBotName", args=_classification_args(properties_path)),
        isolate_scope=True,
    )


def create_bot_operator_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=ast.Call(name="getBotOperator", args=_classification_args(properties_path)),
        isolate_scope=True,
    )
