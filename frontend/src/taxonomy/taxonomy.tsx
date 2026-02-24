import { DataWarehousePopoverField } from 'lib/components/TaxonomicFilter/types'
import {
    UTM_CAMPAIGN_NAME_SCHEMA_FIELD,
    UTM_SOURCE_NAME_SCHEMA_FIELD,
} from 'scenes/web-analytics/tabs/marketing-analytics/utils'

import { CoreFilterDefinition } from '~/types'

import * as coreFilterDefinitionsByGroup from './core-filter-definitions-by-group.json'
import { transformFilterDefinitions } from './transformations'

type CoreFilterDefinitionsGroup = keyof typeof coreFilterDefinitionsByGroup

export const CORE_FILTER_DEFINITIONS_BY_GROUP = Object.entries(coreFilterDefinitionsByGroup).reduce(
    (acc, [key, group]) => {
        if (key === '//' || typeof group === 'string') {
            // ignore the comment
            return acc
        }
        return Object.assign(acc, { [key]: transformFilterDefinitions(group) })
    },
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
const BILLING_PRODUCTS = [
    'data_warehouse',
    'error_tracking',
    'feature_flags',
    'integrations',
    'llm_analytics',
    'logs',
    'platform_and_support',
    'posthog_ai',
    'product_analytics',
    'realtime_destinations',
    'session_replay',
    'surveys',
    'workflows_emails',
] as const

const BILLING_USAGE_CATEGORIES = [
    'current_amount_usd',
    'current_usage',
    'custom_limits',
    'custom_limits_usd',
    'free_allocation',
    'percentage_usage',
    'projected_usage',
    'unit_amount_usd',
    'usage_limit',
] as const

export const CLOUD_INTERNAL_POSTHOG_PROPERTY_KEYS = [
    'billing_period_end',
    'billing_period_start',
    'current_total_amount_usd',
    'customer_deactivated',
    'has_billing_plan',
    'is_demo_project',
    'realm',
    'email_service_available',
    'slack_service_available',
    'commit_sha',
    ...BILLING_USAGE_CATEGORIES.flatMap((category) => BILLING_PRODUCTS.map((product) => `${category}.${product}`)),
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
    $csp_violation: [
        '$csp_document_url',
        '$csp_blocked_url',
        '$csp_effective_directive',
        '$csp_violated_directive',
        '$csp_version',
        '$csp_original_policy',
        '$csp_disposition',
        '$csp_line_number',
        '$csp_column_number',
        '$csp_source_file',
        '$csp_status_code',
        '$csp_referrer',
        '$csp_report_type',
        '$csp_raw_report',
        '$csp_script_sample',
        '$csp_user_agent',
    ],
    $set: ['$set', '$set_once'],
    $exception: [
        '$exception_issue_id',
        '$exception_functions',
        '$exception_sources',
        '$exception_types',
        '$exception_values',
    ],
}
export type KNOWN_PROMOTED_PROPERTY_PARENTS = keyof typeof POSTHOG_EVENT_PROMOTED_PROPERTIES

export function isPostHogProperty(propertyKey: string, isCloudOrDev: boolean | undefined = false): boolean {
    const isPostHogProperty = propertyKey.startsWith('$') || PROPERTY_KEYS.includes(propertyKey)
    const isNonDollarPostHogProperty = isCloudOrDev && CLOUD_INTERNAL_POSTHOG_PROPERTY_KEYS.includes(propertyKey)
    return isPostHogProperty || isNonDollarPostHogProperty
}

export const conversionGoalPopoverFields: DataWarehousePopoverField[] = [
    {
        key: 'timestamp_field',
        label: 'Timestamp Field',
        allowHogQL: true,
    },
    {
        key: 'distinct_id_field',
        label: 'Distinct ID Field',
        allowHogQL: true,
    },
    {
        key: UTM_CAMPAIGN_NAME_SCHEMA_FIELD,
        label: 'UTM Campaign Name',
        type: 'string',
        optional: true,
    },
    {
        key: UTM_SOURCE_NAME_SCHEMA_FIELD,
        label: 'UTM Source Name',
        type: 'string',
        optional: true,
    },
]
