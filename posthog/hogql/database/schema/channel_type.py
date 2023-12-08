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
    properties.$initial_referring_domain = '$direct',
    '$direct',
    dictGetOrNull(
        'channel_definition_dict',
        'domain_type',
        (cutToFirstSignificantSubdomain(coalesce(properties.$initial_referring_domain, '')), 'source')
    )
)
"""
        ),
    )


def create_initial_channel_type(name: str):
    return ExpressionField(
        name=name,
        expr=parse_expr(
            """
multiIf(
    match(properties.$initial_utm_campaign, 'cross-network'),
    'Cross Network',

    (
        match(properties.$initial_utm_medium, '^(.*cp.*|ppc|retargeting|paid.*)$') OR
        properties.$initial_gclid IS NOT NULL OR
        properties.$initial_gad_source IS NOT NULL
    ),
    coalesce(
        dictGetOrNull(
            'channel_definition_dict',
            'type_if_paid',
            (
                coalesce(properties.$initial_utm_source, ''),
                'source'
            )
        ),
        dictGetOrNull(
            'channel_definition_dict',
            'type_if_paid',
            (
                cutToFirstSignificantSubdomain(coalesce(properties.$initial_referring_domain, '')),
                'source'
            )
        ),
        if(
            match(properties.$initial_utm_campaign, '^(.*(([^a-df-z]|^)shop|shopping).*)$'),
            'Paid Shopping',
            NULL
        ),
        dictGetOrNull(
            'channel_definition_dict',
            'type_if_paid',
            (coalesce(properties.$initial_utm_medium, ''), 'medium')
        ),
        multiIf (
            properties.$initial_gad_source = '1',
            'Paid Search',

            match(properties.$initial_utm_campaign, '^(.*video.*)$'),
            'Paid Video',

            'Paid Other'
        )
    ),

    (
        properties.$initial_referring_domain = '$direct'
        AND (properties.$initial_utm_medium IS NULL OR properties.$initial_utm_medium = '')
        AND (properties.$initial_utm_source IS NULL OR properties.$initial_utm_source IN ('', '(direct)', 'direct'))
    ),
    'Direct',

    coalesce(
        dictGetOrNull(
            'channel_definition_dict',
            'type_if_organic',
            (
                coalesce(properties.$initial_utm_source, ''),
                'source'
            )
        ),
        dictGetOrNull(
            'channel_definition_dict',
            'type_if_organic',
            (
                cutToFirstSignificantSubdomain(coalesce(properties.$initial_referring_domain, '')),
                'source'
            )
        ),
        if(
            match(properties.$initial_utm_campaign, '^(.*(([^a-df-z]|^)shop|shopping).*)$'),
            'Organic Shopping',
            NULL
        ),
        dictGetOrNull(
            'channel_definition_dict',
            'type_if_paid',
            (coalesce(properties.$initial_utm_medium, ''), 'medium')
        ),
        multiIf(
            match(properties.$initial_utm_campaign, '^(.*video.*)$'),
            'Organic Video',

              match(properties.$initial_utm_medium, '(push$|mobile|notification)')
                OR properties.$initial_utm_source = 'firebase',
            'Push',

            NULL
        )
    )
)""",
            start=None,
        ),
    )
