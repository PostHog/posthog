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
        properties.$initial_fbclid IS NOT NULL OR
        properties.$initial_gclid IS NOT NULL OR
        properties.$initial_msclkid IS NOT NULL
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
        if (
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
