import { CoreFilterDefinition } from '~/types'

import * as coreFilterDefinitionsByGroup from './core-filter-definitions-by-group.json'
import { transformFilterDefinitions } from './transformations'

type CoreFilterDefinitionsGroup = keyof typeof coreFilterDefinitionsByGroup

export const CORE_FILTER_DEFINITIONS_BY_GROUP = Object.entries(coreFilterDefinitionsByGroup).reduce(
    (acc, [key, group]) => ({
        ...acc,
        [key]: transformFilterDefinitions(group),
    }),
    {} as Record<CoreFilterDefinitionsGroup, Record<string, CoreFilterDefinition>>
)

// We treat `$session_duration` as an event property in the context of series `math`, but it's fake in a sense
CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties.$session_duration =
    CORE_FILTER_DEFINITIONS_BY_GROUP.session_properties.$session_duration

CORE_FILTER_DEFINITIONS_BY_GROUP.numerical_event_properties = CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties

// Change "All Events" to empty string
CORE_FILTER_DEFINITIONS_BY_GROUP.events[''] = CORE_FILTER_DEFINITIONS_BY_GROUP.events['All Events']
delete CORE_FILTER_DEFINITIONS_BY_GROUP.events['All Events']

export const PROPERTY_KEYS = Object.keys(CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties)

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
