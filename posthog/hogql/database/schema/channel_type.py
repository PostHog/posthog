from dataclasses import dataclass
from typing import Optional, Union

from posthog.hogql import ast
from posthog.hogql.database.models import ExpressionField
from posthog.hogql.parser import parse_expr
from posthog.schema import (
    CustomChannelRule,
    CustomChannelOperator,
    CustomChannelField,
)


# Create a virtual field that categories the type of channel that a user was acquired through. Use GA4's definitions as
# a starting point, but also add some custom logic to handle some edge cases that GA4 doesn't handle.
# The source for this logic is:
# UA: https://support.google.com/analytics/answer/3297892?hl=en
# GA4: https://support.google.com/analytics/answer/9756891?hl=en
#
# Some caveats
# - GA4 will "cheat" as it can decode the opaque gclid, but the presence of a gclid means that is an Ad
# - Meta (FB/Instagram) has a fbclid which is also opaque, and added to both paid and organic clicks
# - Mobile Safari is very hard to attribute on, as by default it will strip any ad parameters as well as the referrer
# - We could improve the behaviour with Google Ads by add a plugin to call the Google Ads API
# - We could improve the behaviour on the Apple side by implementing PCM and SKAdNetwork
#   - https://developer.apple.com/app-store/ad-attribution/


@dataclass
class ChannelTypeExprs:
    source: ast.Expr
    medium: ast.Expr
    campaign: ast.Expr
    referring_domain: ast.Expr
    gclid: ast.Expr
    gad_source: ast.Expr


def create_initial_domain_type(name: str):
    return ExpressionField(
        name=name,
        expr=parse_expr(
            """
if(
    {referring_domain} = '$direct',
    '$direct',
    hogql_lookupDomainType({referring_domain})
)
""",
            {
                "referring_domain": ast.Call(
                    name="toString", args=[ast.Field(chain=["properties", "$initial_referring_domain"])]
                )
            },
        ),
    )


def create_initial_channel_type(name: str, custom_rules: Optional[list[CustomChannelRule]] = None):
    return ExpressionField(
        name=name,
        expr=create_channel_type_expr(
            source_exprs=ChannelTypeExprs(
                campaign=ast.Call(name="toString", args=[ast.Field(chain=["properties", "$initial_utm_campaign"])]),
                medium=ast.Call(name="toString", args=[ast.Field(chain=["properties", "$initial_utm_medium"])]),
                source=ast.Call(name="toString", args=[ast.Field(chain=["properties", "$initial_utm_source"])]),
                referring_domain=ast.Call(
                    name="toString", args=[ast.Field(chain=["properties", "$initial_referring_domain"])]
                ),
                gclid=ast.Call(name="toString", args=[ast.Field(chain=["properties", "$initial_gclid"])]),
                gad_source=ast.Call(name="toString", args=[ast.Field(chain=["properties", "$initial_gad_source"])]),
            ),
            custom_rules=custom_rules,
        ),
    )


def custom_condition_to_expr(
    expr: ast.Expr,
    value: Optional[str],
    operator: CustomChannelOperator,
) -> ast.Expr:
    if operator == CustomChannelOperator.EXACT:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=expr,
            right=ast.Constant(value=value),
        )
    elif operator == CustomChannelOperator.IS_NOT:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.NotEq,
            left=expr,
            right=ast.Constant(value=value),
        )
    elif operator == CustomChannelOperator.IS_SET:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.NotEq,
            left=expr,
            right=ast.Constant(value=None),
        )
    elif operator == CustomChannelOperator.IS_NOT_SET:
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=expr,
                right=ast.Constant(value=None),
            )
        ]
        return ast.Or(exprs=exprs)
    elif operator == CustomChannelOperator.ICONTAINS:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.ILike,
            left=expr,
            right=ast.Constant(value=f"%{value}%"),
        )
    elif operator == CustomChannelOperator.NOT_ICONTAINS:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.NotILike,
            left=expr,
            right=ast.Constant(value=f"%{value}%"),
        )
    elif operator == CustomChannelOperator.REGEX:
        return ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="match", args=[ast.Call(name="toString", args=[expr]), ast.Constant(value=value)]),
                ast.Constant(value=0),
            ],
        )
    elif operator == CustomChannelOperator.NOT_REGEX:
        return ast.Call(
            name="ifNull",
            args=[
                ast.Call(
                    name="not",
                    args=[
                        ast.Call(name="match", args=[ast.Call(name="toString", args=[expr]), ast.Constant(value=value)])
                    ],
                ),
                ast.Constant(value=1),
            ],
        )

    else:
        raise NotImplementedError(f"PropertyOperator {operator} not implemented")


def custom_rule_to_expr(custom_rule: CustomChannelRule, source_exprs: ChannelTypeExprs) -> ast.Expr:
    conditions: list[Union[ast.Expr | ast.Call]] = []
    for condition in custom_rule.conditions:
        if condition.key == CustomChannelField.UTM_SOURCE:
            expr = source_exprs.source
        elif condition.key == CustomChannelField.UTM_MEDIUM:
            expr = source_exprs.medium
        elif condition.key == CustomChannelField.UTM_CAMPAIGN:
            expr = source_exprs.campaign
        elif condition.key == CustomChannelField.REFERRING_DOMAIN:
            expr = source_exprs.referring_domain
        else:
            raise NotImplementedError(f"Property {condition.key} not implemented")
        value = condition.value
        if isinstance(value, list):
            if len(value) == 0:
                continue
            elif len(value) == 1:
                conditions.append(custom_condition_to_expr(expr, value[0], condition.op))
            else:
                conditions.append(
                    ast.Call(name="or", args=[custom_condition_to_expr(expr, val, condition.op) for val in value])
                )
        else:
            conditions.append(custom_condition_to_expr(expr, value, condition.op))
    if len(conditions) == 0:
        return ast.Constant(value=True)
    elif len(conditions) == 1:
        return conditions[0]
    else:
        return ast.Call(name=custom_rule.combiner.lower(), args=conditions)


def create_channel_type_expr(
    custom_rules: Optional[list[CustomChannelRule]], source_exprs: ChannelTypeExprs
) -> ast.Expr:
    def wrap_with_null_if_empty(expr: ast.Expr) -> ast.Expr:
        return ast.Call(
            name="nullIf",
            args=[ast.Call(name="nullIf", args=[expr, ast.Constant(value="")]), ast.Constant(value="null")],
        )

    def wrap_with_lower(expr: ast.Expr) -> ast.Expr:
        return ast.Call(
            name="lower",
            args=[expr],
        )

    custom_rule_expr: Optional[ast.Expr] = None
    if custom_rules:
        if_args = []
        for rule in custom_rules:
            if_args.append(custom_rule_to_expr(rule, source_exprs))
            if_args.append(ast.Constant(value=rule.channel_type))
        if_args.append(ast.Constant(value=None))
        custom_rule_expr = ast.Call(name="multiIf", args=if_args)

    # This logic is referenced in our docs https://posthog.com/docs/data/channel-type, be sure to update both if you
    # update either.
    builtin_rules = parse_expr(
        """
multiIf(
    match({campaign}, 'cross-network'),
    'Cross Network',

    (
        {medium} IN ('cpc', 'cpm', 'cpv', 'cpa', 'ppc', 'retargeting') OR
        startsWith({medium}, 'paid') OR
        {gclid} IS NOT NULL OR
        {gad_source} IS NOT NULL
    ),
    coalesce(
        hogql_lookupPaidSourceType({source}),
        if(
            match({campaign}, '^(.*(([^a-df-z]|^)shop|shopping).*)$'),
            'Paid Shopping',
            NULL
        ),
        hogql_lookupPaidMediumType({medium}),
        hogql_lookupPaidSourceType({referring_domain}),
        multiIf (
            {gad_source} = '1',
            'Paid Search',

            match({campaign}, '^(.*video.*)$'),
            'Paid Video',

            'Paid Unknown'
        )
    ),

    (
        {referring_domain} = '$direct'
        AND ({medium} IS NULL)
        AND ({source} IS NULL OR {source} IN ('(direct)', 'direct', '$direct'))
    ),
    'Direct',

    coalesce(
        hogql_lookupOrganicSourceType({source}),
        if(
            match({campaign}, '^(.*(([^a-df-z]|^)shop|shopping).*)$'),
            'Organic Shopping',
            NULL
        ),
        hogql_lookupOrganicMediumType({medium}),
        hogql_lookupOrganicSourceType({referring_domain}),
        multiIf(
            match({campaign}, '^(.*video.*)$'),
            'Organic Video',

            match({medium}, 'push$'),
            'Push',

            {referring_domain} == '$direct',
            'Direct',

            {referring_domain} IS NOT NULL,
            'Referral',

            'Unknown'
        )
    )
)""",
        start=None,
        placeholders={
            "campaign": wrap_with_lower(wrap_with_null_if_empty(source_exprs.campaign)),
            "medium": wrap_with_lower(wrap_with_null_if_empty(source_exprs.medium)),
            "source": wrap_with_lower(wrap_with_null_if_empty(source_exprs.source)),
            "referring_domain": source_exprs.referring_domain,
            "gclid": wrap_with_null_if_empty(source_exprs.gclid),
            "gad_source": wrap_with_null_if_empty(source_exprs.gad_source),
        },
    )
    if custom_rule_expr:
        return ast.Call(
            name="coalesce",
            args=[custom_rule_expr, builtin_rules],
        )
    else:
        return builtin_rules


POSSIBLE_CHANNEL_TYPES = [
    "Cross Network",
    "Paid Search",
    "Paid Social",
    "Paid Video",
    "Paid Shopping",
    "Paid Unknown",
    "Direct",
    "Organic Search",
    "Organic Social",
    "Organic Video",
    "Organic Shopping",
    "Push",
    "SMS",
    "Audio",
    "Email",
    "Referral",
    "Affiliate",
    "Unknown",
]
