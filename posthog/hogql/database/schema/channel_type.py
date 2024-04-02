from posthog.hogql import ast
from posthog.hogql.database.models import ExpressionField
from posthog.hogql.parser import parse_expr


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


def create_channel_type_expr(
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
        hogql_lookupPaidDomainType({referring_domain}),
        if(
            match({campaign}, '^(.*(([^a-df-z]|^)shop|shopping).*)$'),
            'Paid Shopping',
            NULL
        ),
        hogql_lookupPaidMediumType({medium}),
        multiIf (
            {gad_source} = '1',
            'Paid Search',

            match({campaign}, '^(.*video.*)$'),
            'Paid Video',

            'Paid Other'
        )
    ),

    (
        {referring_domain} = '$direct'
        AND ({medium} IS NULL)
        AND ({source} IS NULL OR {source} IN ('(direct)', 'direct'))
    ),
    'Direct',

    coalesce(
        hogql_lookupOrganicSourceType({source}),
        hogql_lookupOrganicDomainType({referring_domain}),
        if(
            match({campaign}, '^(.*(([^a-df-z]|^)shop|shopping).*)$'),
            'Organic Shopping',
            NULL
        ),
        hogql_lookupOrganicMediumType({medium}),
        multiIf(
            match({campaign}, '^(.*video.*)$'),
            'Organic Video',

            match({medium}, 'push$'),
            'Push',

            'Other'
        )
    )
)""",
        start=None,
        placeholders={
            "campaign": wrap_with_null_if_empty(campaign),
            "medium": wrap_with_null_if_empty(medium),
            "source": wrap_with_null_if_empty(source),
            "referring_domain": referring_domain,
            "gclid": wrap_with_null_if_empty(gclid),
            "gad_source": wrap_with_null_if_empty(gad_source),
        },
    )
