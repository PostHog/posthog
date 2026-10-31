import type { DataWarehousePopoverField } from 'lib/components/TaxonomicFilter/types'

import { UTM_CAMPAIGN_NAME_SCHEMA_FIELD, UTM_SOURCE_NAME_SCHEMA_FIELD } from '~/taxonomy/marketingAnalytics'
import { CoreFilterDefinition } from '~/types'

import type coreFilterDefinitionsJson from './core-filter-definitions-by-group.json'
import { transformFilterDefinitions } from './transformations'

type CoreFilterDefinitionsJson = typeof coreFilterDefinitionsJson
export type CoreFilterDefinitionsGroup = Exclude<keyof CoreFilterDefinitionsJson, '//'>

// The Record type makes typecheck fail when the taxonomy gains or loses a group.
const GROUPS: Record<CoreFilterDefinitionsGroup, true> = {
    elements: true,
    error_tracking_issues: true,
    event_metadata: true,
    event_properties: true,
    events: true,
    groups: true,
    log_entries: true,
    mcp_properties: true,
    metadata: true,
    numerical_event_properties: true,
    person_metadata: true,
    person_properties: true,
    replay: true,
    revenue_analytics_properties: true,
    session_properties: true,
}

// Filled in place, so a module can keep a reference to it or to one of its groups.
export const CORE_FILTER_DEFINITIONS_BY_GROUP = Object.fromEntries(
    Object.keys(GROUPS).map((group) => [group, {}])
) as Record<CoreFilterDefinitionsGroup, Record<string, CoreFilterDefinition>>
CORE_FILTER_DEFINITIONS_BY_GROUP.numerical_event_properties = CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties

export const PROPERTY_KEYS: string[] = []

let definitionsLoaded = false

export function setCoreFilterDefinitions(definitionsByGroup: CoreFilterDefinitionsJson): void {
    if (definitionsLoaded) {
        return
    }
    for (const [key, group] of Object.entries(definitionsByGroup)) {
        if (key === '//' || typeof group === 'string') {
            // ignore the comment
            continue
        }
        Object.assign(
            CORE_FILTER_DEFINITIONS_BY_GROUP[key as CoreFilterDefinitionsGroup],
            transformFilterDefinitions(group)
        )
    }
    const { events, event_properties, session_properties } = CORE_FILTER_DEFINITIONS_BY_GROUP
    // We treat `$session_duration` as an event property in the context of series `math`, but it's fake in a sense
    event_properties.$session_duration = session_properties.$session_duration

    // Change "All Events" to empty string
    events[''] = events['All Events']
    delete events['All Events']

    PROPERTY_KEYS.push(...Object.keys(event_properties))
    definitionsLoaded = true
}

/** Wraps a value computed from the taxonomy. It is cached once the taxonomy has loaded, and computed fresh until then. */
export function deriveFromCoreFilterDefinitions<T>(derive: () => T): () => T {
    let derived: { value: T } | null = null
    return () => {
        if (derived) {
            return derived.value
        }
        const value = derive()
        if (definitionsLoaded) {
            derived = { value }
        }
        return value
    }
}

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
    $exception: ['$exception_functions', '$exception_sources', '$exception_types', '$exception_values'],
    $mcp_tool_call: [
        '$mcp_tool_name',
        '$mcp_tool_category',
        '$mcp_is_error',
        '$mcp_error_type',
        '$mcp_duration_ms',
        '$mcp_client_name',
        '$mcp_llm_model',
        '$mcp_intent',
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
    },
    {
        key: UTM_SOURCE_NAME_SCHEMA_FIELD,
        label: 'UTM Source Name',
        type: 'string',
    },
]
