# Create a virtual field that uses GA's channel grouping logic to group events into acquisition channels.
# The source for this logic is:
# UA: https://support.google.com/analytics/answer/3297892?hl=en
# GA4: https://support.google.com/analytics/answer/9756891?hl=en

# I'm not fully convinced that this approach will work on its own, as GA4 will have a lot more information on paid ads
# than what we will have access to. We'll need to get this live and see what it looks like on Posthog data.
from posthog.hogql.database.models import ExpressionField
from posthog.hogql.parser import parse_expr


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
        'type',
        cutToFirstSignificantSubdomain(coalesce(properties.$initial_referring_domain, ''))
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

    match(properties.$initial_utm_medium, '^(.*cp.*|ppc|retargeting|paid.*)$'),
    CASE dictGetOrNull('channel_definition_dict', 'type', cutToFirstSignificantSubdomain(coalesce(properties.$initial_referring_domain, '')))
        WHEN 'Shopping' THEN 'Paid Shopping'
        WHEN 'Search' THEN 'Paid Search'
        WHEN 'Video' THEN 'Paid Video'
        WHEN 'Social' THEN 'Paid Social'
        ELSE multiIf(
            match(properties.$initial_utm_campaign, '^(.*(([^a-df-z]|^)shop|shopping).*)$'),
            'Paid Shopping',
            properties.$initial_utm_medium IN
                ('display', 'banner', 'expandable', 'interstitial', 'cpm'),
            'Display',
            'Paid Other'
            )
    END,

    properties.$initial_referring_domain = '$direct' AND (properties.$initial_utm_medium IS NULL OR properties.$initial_utm_medium = ''),
    'Direct',

    CASE dictGetOrNull('channel_definition_dict', 'type', cutToFirstSignificantSubdomain(coalesce(properties.$initial_referring_domain, '')))
        WHEN 'Shopping' THEN 'Organic Shopping'
        WHEN 'Search' THEN 'Organic Search'
        WHEN 'Video' THEN 'Organic Video'
        WHEN 'Social' THEN 'Organic Social'
        ELSE multiIf(
            match(properties.$initial_utm_campaign, '^(.*(([^a-df-z]|^)shop|shopping).*)$'),
            'Organic Shopping',
            properties.$initial_utm_medium IN
                ('social', 'social-network', 'social-media', 'sm', 'social network', 'social media'),
            'Organic Social',
            match(properties.$initial_utm_campaign, '^(.*video.*)$'),
            'Organic Video',
            properties.$initial_utm_medium = 'organic',
            'Organic Search',
            properties.$initial_utm_medium IN ('referral', 'app', 'link'),
            'Referral',
            properties.$initial_utm_source IN ('email', 'e-mail', 'e_mail', 'e mail')
                OR properties.$initial_utm_medium IN ('email', 'e-mail', 'e_mail', 'e mail'),
            'Email',
            properties.$initial_utm_medium = 'affiliate',
            'Affiliate',
            properties.$initial_utm_medium = 'audio',
            'Audio',
            properties.$initial_utm_source = 'sms' OR properties.$initial_utm_medium = 'sms',
            'SMS',
            match(properties.$initial_utm_medium, '(push$|mobile|notification)')
                OR properties.$initial_utm_source = 'firebase',
            'Push',
            NULL
        )
    END
)""",
            start=None,
        ),
    )
