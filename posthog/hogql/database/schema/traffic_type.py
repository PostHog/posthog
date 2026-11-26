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


# Logs carry the request in OpenTelemetry semantic-convention attributes. A log line without a
# user agent is application output, not a request, so every field is NULL for it: bot and human
# filters both leave it out, where the empty-user-agent rule would count it as a bot.
def _log_attribute(key: str) -> ast.Expr:
    # A bare read of the type-suffixed backing map touches only the bucket that holds the key.
    return ast.Call(
        name="arrayElement", args=[ast.Field(chain=["attributes_map_str"]), ast.Constant(value=f"{key}__str")]
    )


def _log_classification_field(name: str, function_name: str) -> ExpressionField:
    user_agent = _log_attribute("user_agent.original")
    return ExpressionField(
        name=name,
        expr=ast.Call(
            name="if",
            args=[
                ast.Call(name="empty", args=[user_agent]),
                ast.Constant(value=None),
                ast.Call(name=function_name, args=[user_agent, _log_attribute("client.address")]),
            ],
        ),
        isolate_scope=True,
    )


def log_traffic_fields() -> dict[str, ExpressionField]:
    return {
        name: _log_classification_field(name, function_name)
        for name, function_name in [
            ("$virt_is_bot", "isLikelyBot"),
            ("$virt_traffic_type", "getTrafficType"),
            ("$virt_traffic_category", "getTrafficCategory"),
            ("$virt_bot_name", "getBotName"),
            ("$virt_bot_operator", "getBotOperator"),
        ]
    }
