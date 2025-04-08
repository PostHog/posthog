/** Same as https://github.com/PostHog/posthog-js/blob/master/src/utils/event-utils.ts */
// Ideally this would be imported from posthog-js, we just need to start exporting the list there
export const CAMPAIGN_PROPERTIES: string[] = [
    'utm_source',
    'utm_medium',
    'utm_campaign',
    'utm_content',
    'utm_term',
    'gclid', // google ads
    'gad_source', // google ads
    'gclsrc', // google ads 360
    'dclid', // google display ads
    'gbraid', // google ads, web to app
    'wbraid', // google ads, app to web
    'fbclid', // facebook
    'msclkid', // microsoft
    'twclid', // twitter
    'li_fat_id', // linkedin
    'mc_cid', // mailchimp campaign id
    'igshid', // instagram
    'ttclid', // tiktok
    'rdt_cid', // reddit
    'irclid', // impact
    '_kx', // klaviyo
]

export const SESSION_INITIAL_PROPERTIES_ADAPTED_FROM_EVENTS = new Set([
    '$referring_domain',
    'utm_source',
    'utm_campaign',
    'utm_medium',
    'utm_content',
    'utm_term',
    'gclid',
    'gad_source',
    'gclsrc',
    'dclid',
    'gbraid',
    'wbraid',
    'fbclid',
    'msclkid',
    'twclid',
    'li_fat_id',
    'mc_cid',
    'igshid',
    'ttclid',
    'rdt_cid',
    'irclid',
    '_kx',
])

export const SESSION_PROPERTIES_ALSO_INCLUDED_IN_EVENTS = new Set([
    '$current_url', // Gets renamed to just $url
    '$host',
    '$pathname',
    '$referrer',
    ...SESSION_INITIAL_PROPERTIES_ADAPTED_FROM_EVENTS,
])

/**
 * these are properties that PostHog add to events they track for their own purposes
 * not part of the general taxonomy
 * but often more numerous than actual properties set on events and useful to hide
 * to make those properties discoverable
 */
export const CLOUD_INTERNAL_POSTHOG_PROPERTY_KEYS = [
    'billing_period_end',
    'billing_period_start',
    'current_amount_usd.data_warehouse',
    'current_amount_usd.feature_flags',
    'current_amount_usd.integrations',
    'current_amount_usd.platform_and_support',
    'current_amount_usd.product_analytics',
    'current_amount_usd.session_replay',
    'current_amount_usd.surveys',
    'current_total_amount_usd',
    'current_usage.data_warehouse',
    'current_usage.feature_flags',
    'current_usage.integrations',
    'current_usage.platform_and_support',
    'current_usage.product_analytics',
    'current_usage.session_replay',
    'current_usage.surveys',
    'customer_deactivated',
    'custom_limits.data_warehouse',
    'custom_limits.feature_flags',
    'custom_limits.integrations',
    'custom_limits.platform_and_support',
    'custom_limits.product_analytics',
    'custom_limits.session_replay',
    'custom_limits.surveys',
    'custom_limits_usd.data_warehouse',
    'custom_limits_usd.feature_flags',
    'custom_limits_usd.integrations',
    'custom_limits_usd.platform_and_support',
    'custom_limits_usd.product_analytics',
    'custom_limits_usd.session_replay',
    'custom_limits_usd.surveys',
    'free_allocation.data_warehouse',
    'free_allocation.feature_flags',
    'free_allocation.integrations',
    'free_allocation.platform_and_support',
    'free_allocation.product_analytics',
    'free_allocation.session_replay',
    'free_allocation.surveys',
    'has_billing_plan',
    'percentage_usage.data_warehouse',
    'percentage_usage.feature_flags',
    'percentage_usage.integrations',
    'percentage_usage.platform_and_support',
    'percentage_usage.product_analytics',
    'percentage_usage.session_replay',
    'percentage_usage.surveys',
    'projected_usage.data_warehouse',
    'projected_usage.feature_flags',
    'projected_usage.integrations',
    'projected_usage.platform_and_support',
    'projected_usage.product_analytics',
    'projected_usage.session_replay',
    'projected_usage.surveys',
    'unit_amount_usd.data_warehouse',
    'unit_amount_usd.feature_flags',
    'unit_amount_usd.integrations',
    'unit_amount_usd.platform_and_support',
    'unit_amount_usd.product_analytics',
    'unit_amount_usd.session_replay',
    'unit_amount_usd.surveys',
    'usage_limit.data_warehouse',
    'usage_limit.feature_flags',
    'usage_limit.integrations',
    'usage_limit.platform_and_support',
    'usage_limit.product_analytics',
    'usage_limit.session_replay',
    'usage_limit.surveys',
    'is_demo_project',
    'realm',
    'email_service_available',
    'slack_service_available',
    'commit_sha',
]

export const POSTHOG_EVENT_PROMOTED_PROPERTIES = {
    $pageview: ['$current_url', 'title', '$referrer'],
    $pageleave: ['$current_url', 'title', '$referrer'],
    $groupidentify: ['$group_type', '$group_key', '$group_set'],
    $screen: ['$screen_name'],
    $web_vitals: [
        '$web_vitals_FCP_value',
        '$web_vitals_CLS_value',
        '$web_vitals_INP_value',
        '$web_vitals_LCP_value',
        '$web_vitals_FCP_event',
        '$web_vitals_CLS_event',
        '$web_vitals_INP_event',
        '$web_vitals_LCP_event',
    ],
    $set: ['$set', '$set_once'],
}
export type KNOWN_PROMOTED_PROPERTY_PARENTS = keyof typeof POSTHOG_EVENT_PROMOTED_PROPERTIES
