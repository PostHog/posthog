from typing import Optional

from posthog.hogql import ast
from posthog.hogql.database.models import ExpressionField
from posthog.hogql.parser import parse_expr
from posthog.schema import CustomChannelRule, CustomChannelCondition, PropertyOperator


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


def create_initial_channel_type(name: str):
    return ExpressionField(
        name=name,
        expr=create_channel_type_expr(
            campaign=ast.Call(name="toString", args=[ast.Field(chain=["properties", "$initial_utm_campaign"])]),
            medium=ast.Call(name="toString", args=[ast.Field(chain=["properties", "$initial_utm_medium"])]),
            source=ast.Call(name="toString", args=[ast.Field(chain=["properties", "$initial_utm_source"])]),
            referring_domain=ast.Call(
                name="toString", args=[ast.Field(chain=["properties", "$initial_referring_domain"])]
            ),
            gclid=ast.Call(name="toString", args=[ast.Field(chain=["properties", "$initial_gclid"])]),
            gad_source=ast.Call(name="toString", args=[ast.Field(chain=["properties", "$initial_gad_source"])]),
        ),
    )


def custom_condition_to_expr(
    custom_condition: CustomChannelCondition,
    campaign: ast.Expr,
    medium: ast.Expr,
    source: ast.Expr,
    referring_domain: ast.Expr,
) -> ast.Expr:
    operator = custom_condition.operator
    value = custom_condition.value

    if custom_condition.property == "campaign":
        expr = campaign
    elif custom_condition.property == "medium":
        expr = medium
    elif custom_condition.property == "source":
        expr = source
    elif custom_condition.property == "referring_domain":
        expr = referring_domain
    else:
        raise NotImplementedError(f"Property {custom_condition.property} not implemented")

    if operator == PropertyOperator.IS_SET:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.NotEq,
            left=expr,
            right=ast.Constant(value=None),
        )
    elif operator == PropertyOperator.IS_NOT_SET:
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=expr,
                right=ast.Constant(value=None),
            )
        ]

        return ast.Or(exprs=exprs)
    elif operator == PropertyOperator.ICONTAINS:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.ILike,
            left=expr,
            right=ast.Constant(value=f"%{value}%"),
        )
    elif operator == PropertyOperator.NOT_ICONTAINS:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.NotILike,
            left=expr,
            right=ast.Constant(value=f"%{value}%"),
        )
    elif operator == PropertyOperator.REGEX:
        return ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="match", args=[ast.Call(name="toString", args=[expr]), ast.Constant(value=value)]),
                ast.Constant(value=0),
            ],
        )
    elif operator == PropertyOperator.NOT_REGEX:
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
    elif operator == PropertyOperator.EXACT:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=expr,
            right=ast.Constant(value=value),
        )
    elif operator == PropertyOperator.IS_NOT:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.NotEq,
            left=expr,
            right=ast.Constant(value=value),
        )
    elif operator == PropertyOperator.LT:
        return ast.CompareOperation(op=ast.CompareOperationOp.Lt, left=expr, right=ast.Constant(value=value))
    elif operator == PropertyOperator.GT:
        return ast.CompareOperation(op=ast.CompareOperationOp.Gt, left=expr, right=ast.Constant(value=value))
    elif operator == PropertyOperator.LTE:
        return ast.CompareOperation(op=ast.CompareOperationOp.LtEq, left=expr, right=ast.Constant(value=value))
    elif operator == PropertyOperator.GTE:
        return ast.CompareOperation(op=ast.CompareOperationOp.GtEq, left=expr, right=ast.Constant(value=value))
    else:
        raise NotImplementedError(f"PropertyOperator {operator} not implemented")


def custom_rule_to_expr(
    custom_rule: CustomChannelRule,
    campaign: ast.Expr,
    medium: ast.Expr,
    source: ast.Expr,
    referring_domain: ast.Expr,
) -> ast.Expr:
    conditions = []
    for condition in custom_rule.conditions:
        conditions.append(custom_condition_to_expr(condition, campaign, medium, source, referring_domain))
    return ast.Call(name=custom_rule.combiner, args=conditions)


def create_channel_type_expr(
    custom_rules: Optional[list[CustomChannelRule]],
    campaign: ast.Expr,
    medium: ast.Expr,
    source: ast.Expr,
    referring_domain: ast.Expr,
    gclid: ast.Expr,
    gad_source: ast.Expr,
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
        custom_rule_expr = custom_rule_expr

    # This logic is referenced in our docs https://posthog.com/docs/data/channel-type, be sure to update both if you
    # update either.
    return parse_expr(
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
            "campaign": wrap_with_lower(wrap_with_null_if_empty(campaign)),
            "medium": wrap_with_lower(wrap_with_null_if_empty(medium)),
            "source": wrap_with_lower(wrap_with_null_if_empty(source)),
            "referring_domain": referring_domain,
            "gclid": wrap_with_null_if_empty(gclid),
            "gad_source": wrap_with_null_if_empty(gad_source),
        },
    )


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
