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


# Native mobile SDKs never send $raw_user_agent, and capture does not fill it from the request
# header. Their events reach the empty-user-agent path and default to Automation/bot. $lib names
# the SDK, so it separates native app traffic from mobile web (which does send a user agent).
NATIVE_MOBILE_SDK_LIBS = (
    "posthog-android",
    "posthog-ios",
    "posthog-react-native",
    "posthog-flutter",
    "posthog-kmp",
)


def _lib_expr(properties_path: Optional[list[str]] = None) -> ast.Expr:
    if not properties_path:
        properties_path = ["properties"]
    return ast.Field(chain=[*properties_path, "$lib"])


def _with_mobile_sdk_override(
    classification_expr: ast.Expr, regular_value: bool | str, properties_path: Optional[list[str]] = None
) -> ast.Expr:
    """Skip bot classification for native mobile SDK events.

    A native mobile SDK ($lib in NATIVE_MOBILE_SDK_LIBS) sends no $raw_user_agent, so the
    empty-user-agent path can't tell its events apart from a headless crawler with no user
    agent and defaults every one to Automation/bot. Short-circuit to the regular-traffic
    verdict for these events instead.
    """
    return ast.Call(
        name="if",
        args=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Call(name="ifNull", args=[_lib_expr(properties_path), ast.Constant(value="")]),
                right=ast.Array(exprs=[ast.Constant(value=lib) for lib in NATIVE_MOBILE_SDK_LIBS]),
            ),
            ast.Constant(value=regular_value),
            classification_expr,
        ],
    )


# These one-node calls are expanded to the classification SQL in the resolver (see Resolver.visit_call),
# so the big expression only materializes for queries that select the field.
def create_is_bot_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=_with_mobile_sdk_override(
            ast.Call(name="isLikelyBot", args=_classification_args(properties_path)), False, properties_path
        ),
        isolate_scope=True,
    )


def create_traffic_type_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=_with_mobile_sdk_override(
            ast.Call(name="getTrafficType", args=_classification_args(properties_path)), "Regular", properties_path
        ),
        isolate_scope=True,
    )


def create_traffic_category_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=_with_mobile_sdk_override(
            ast.Call(name="getTrafficCategory", args=_classification_args(properties_path)), "regular", properties_path
        ),
        isolate_scope=True,
    )


def create_bot_name_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=_with_mobile_sdk_override(
            ast.Call(name="getBotName", args=_classification_args(properties_path)), "", properties_path
        ),
        isolate_scope=True,
    )


def create_bot_operator_field(name: str, properties_path: Optional[list[str]] = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=_with_mobile_sdk_override(
            ast.Call(name="getBotOperator", args=_classification_args(properties_path)), "", properties_path
        ),
        isolate_scope=True,
    )
