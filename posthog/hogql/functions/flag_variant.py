from typing import List

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import HogQLException
from posthog.hogql.parser import parse_expr


def flag_variant(node: ast.Expr, args: List[ast.Expr], context: HogQLContext) -> ast.Expr:
    flag_key = args[0]
    distinct_id = args[1]
    if not isinstance(flag_key, ast.Constant):
        raise HogQLException("flag_variant(flag_key, distinct_id) takes only a constant for flag_key", node=flag_key)

    from posthog.models import FeatureFlag

    if isinstance(flag_key.value, str):
        feature_flags = FeatureFlag.objects.filter(key=flag_key.value, team_id=context.team_id)
        if len(feature_flags) == 1:
            feature_flag = feature_flags[0]
            variants = feature_flag.variants

            if len(variants) == 0:
                return ast.Constant(value=None)

            variant_uint64 = parse_expr(
                "reinterpretAsUInt64(reverse(unhex(substring(SHA1(concat({key}, '.', {distinct_id}, {salt})), 1, 15))))",
                placeholders={
                    "key": ast.Constant(value=feature_flag.key),
                    "distinct_id": distinct_id,
                    "salt": ast.Constant(value=""),
                },
            )

            variant_min = 0
            args = []
            for variant in variants:
                condition = parse_expr(
                    "{v} < {max}",
                    placeholders={
                        "v": variant_uint64,
                        "max": ast.Constant(value=variant_min + variant["rollout_percentage"] / 100),
                    },
                )
                variant_min = variant_min + variant["rollout_percentage"] / 100
                args.append(condition)
                args.append(ast.Constant(value=variant["key"]))

            return ast.Call(name="multiIf", args=[*args, ast.Constant(value=None)])

        raise HogQLException(f"Could not find feature flag with key '{flag_key.value}'", node=flag_key)

    raise HogQLException("The first argument to flag_variant() must be a string", node=flag_key)
