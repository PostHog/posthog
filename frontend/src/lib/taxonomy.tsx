import { getAppContext } from 'lib/utils/getAppContext'

import { CoreFilterDefinition, PropertyFilterValue } from '~/types'

import { TaxonomicFilterGroupType } from './components/TaxonomicFilter/types'
import { Link } from './lemon-ui/Link'

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
]

// copy from https://github.com/PostHog/posthog/blob/29ac8d6b2ba5de4b65a148136b681b8e52e20429/plugin-server/src/utils/db/utils.ts#L44
const PERSON_PROPERTIES_ADAPTED_FROM_EVENT = new Set([
    // mobile params
    '$app_build',
    '$app_name',
    '$app_namespace',
    '$app_version',
    // web params
    '$browser',
    '$browser_version',
    '$device_type',
    '$current_url',
    '$pathname',
    '$os',
    '$os_version',
    '$referring_domain',
    '$referrer',
    ...CAMPAIGN_PROPERTIES,
])

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
])

// event property definitions are used in the API to search and so are defined in python and set on the app_context
// so we need to patch JSX descriptions into them here
const eventPropertiesFromAppContext = getAppContext()?.event_property_definitions || {}
try {
    eventPropertiesFromAppContext['$plugins_succeeded'].description = (
        <>
            Plugins that successfully processed the event, e.g. edited properties (plugin method{' '}
            <code>processEvent</code>).
        </>
    )
    eventPropertiesFromAppContext['$plugins_failed'].description = (
        <>
            Plugins that failed to process the event (plugin method <code>processEvent</code>).
        </>
    )
    eventPropertiesFromAppContext['$plugins_deferred'].description = (
        <>
            Plugins to which the event was handed off post-ingestion, e.g. for export (plugin method{' '}
            <code>onEvent</code>).
        </>
    )
    eventPropertiesFromAppContext['$user_id'].description = (
        <span>
            This variable will be set to the distinct ID if you've called{' '}
            <pre className="inline">posthog.identify('distinct id')</pre>. If the user is anonymous, it'll be empty.
        </span>
    )
    eventPropertiesFromAppContext['$feature_flag'].description = (
        <>
            The feature flag that was called.
            <br />
            <br />
            Warning! This only works in combination with the $feature_flag_called event. If you want to filter other
            events, try "Active Feature Flags".
        </>
    )
} catch (e) {
    console.error('Could not set JSX descriptions for event properties', e)
}
export const CORE_FILTER_DEFINITIONS_BY_GROUP = {
    events: {
        '': {
            label: 'All events',
            description: 'This is a wildcard that matches all events.',
        },
        $pageview: {
            label: 'Pageview',
            description: 'When a user loads (or reloads) a page.',
        },
        $pageleave: {
            label: 'Pageleave',
            description: 'When a user leaves a page.',
        },
        $autocapture: {
            label: 'Autocapture',
            description: 'User interactions that were automatically captured.',
            examples: ['clicked button'],
        },
        $$heatmap: {
            label: 'Heatmap',
            description: 'Heatmap events carry heatmap data to the backend, they do not contribute to event counts.',
        },
        $copy_autocapture: {
            label: 'Clipboard autocapture',
            description: 'Selected text automatically captured when a user copies or cuts.',
        },
        $screen: {
            label: 'Screen',
            description: 'When a user loads a screen in a mobile app.',
        },
        $set: {
            label: 'Set',
            description: 'Setting person properties.',
        },
        $opt_in: {
            label: 'Opt In',
            description: 'When a user opts into analytics.',
        },
        $feature_flag_called: {
            label: 'Feature Flag Called',
            description: (
                <>
                    The feature flag that was called.
                    <br />
                    <br />
                    Warning! This only works in combination with the $feature_flag event. If you want to filter other
                    events, try "Active Feature Flags".
                </>
            ),
            examples: ['beta-feature'],
        },
        $feature_view: {
            label: 'Feature View',
            description: 'When a user views a feature.',
        },
        $feature_interaction: {
            label: 'Feature Interaction',
            description: 'When a user interacts with a feature.',
        },
        $feature_enrollment_update: {
            label: 'Feature Enrollment',
            description: 'When a user enrolls with a feature.',
        },
        $capture_metrics: {
            label: 'Capture Metrics',
            description: 'Metrics captured with values pertaining to your systems at a specific point in time',
        },
        $identify: {
            label: 'Identify',
            description: 'A user has been identified with properties',
        },
        $create_alias: {
            label: 'Alias',
            description: 'An alias ID has been added to a user',
        },
        $merge_dangerously: {
            label: 'Merge',
            description: 'An alias ID has been added to a user',
        },
        $groupidentify: {
            label: 'Group Identify',
            description: 'A group has been identified with properties',
        },
        $rageclick: {
            label: 'Rageclick',
            description: 'A user has rapidly and repeatedly clicked in a single place',
        },
        $dead_click: {
            label: 'Dead click',
            description: 'A user has clicked on something that is probably not clickable',
        },
        $exception: {
            label: 'Exception',
            description: 'Exceptions - an error or unexpected event in your application',
        },
        $web_vitals: {
            label: 'Web Vitals',
            description: 'Automatically captured web vitals data',
        },
        // Mobile SDKs events
        'Application Opened': {
            label: 'Application Opened',
            description: 'When a user opens the mobile app either for the first time or from the foreground.',
        },
        'Application Backgrounded': {
            label: 'Application Backgrounded',
            description: 'When a user puts the mobile app in the background.',
        },
        'Application Updated': {
            label: 'Application Updated',
            description: 'When a user upgrades the mobile app.',
        },
        'Application Installed': {
            label: 'Application Installed',
            description: 'When a user installs the mobile app.',
        },
        'Application Became Active': {
            label: 'Application Became Active',
            description: 'When a user puts the mobile app in the foreground.',
        },
        'Deep Link Opened': {
            label: 'Deep Link Opened',
            description: 'When a user opens the mobile app via a deep link.',
        },
    },
    elements: {
        tag_name: {
            label: 'Tag Name',
            description: 'HTML tag name of the element which you want to filter.',
            examples: ['a', 'button', 'input'],
        },
        selector: {
            label: 'CSS Selector',
            description: 'Select any element by CSS selector.',
            examples: ['div > a', 'table td:nth-child(2)', '.my-class'],
        },
        text: {
            label: 'Text',
            description: 'Filter on the inner text of the HTML element.',
        },
        href: {
            label: 'Target (href)',
            description: (
                <span>
                    Filter on the <code>href</code> attribute of the element.
                </span>
            ),
            examples: ['https://posthog.com/about'],
        },
    },
    metadata: {
        distinct_id: {
            label: 'Distinct ID',
            description: 'The current distinct ID of the user.',
            examples: ['16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
        },
        timestamp: {
            label: 'Timestamp',
            description: 'Time the event happened.',
            examples: ['2023-05-20T15:30:00Z'],
            system: true,
        },
        event: {
            label: 'Event',
            description: 'The name of the event.',
            examples: ['$pageview'],
            system: true,
        },
    },
    event_properties: eventPropertiesFromAppContext,
    numerical_event_properties: {}, // Same as event properties, see assignment below
    person_properties: {}, // Currently person properties are the same as event properties, see assignment below
    session_properties: {
        $session_duration: {
            label: 'Session duration',
            description: (
                <span>
                    The duration of the session being tracked. Learn more about how PostHog tracks sessions in{' '}
                    <Link to="https://posthog.com/docs/user-guides/sessions">our documentation.</Link>
                    <br /> <br />
                    Note, if the duration is formatted as a single number (not 'HH:MM:SS'), it's in seconds.
                </span>
            ),
            examples: ['01:04:12'],
        },
        $start_timestamp: {
            label: 'Start timestamp',
            description: 'The timestamp of the first event from this session.',
            examples: [new Date().toISOString()],
        },
        $end_timestamp: {
            label: 'End timestamp',
            description: 'The timestamp of the last event from this session',
            examples: [new Date().toISOString()],
        },
        $entry_current_url: {
            label: 'Entry URL',
            description: 'The first URL visited in this session.',
            examples: ['https://example.com/interesting-article?parameter=true'],
        },
        $entry_pathname: {
            label: 'Entry pathname',
            description: 'The first pathname visited in this session.',
            examples: ['/interesting-article?parameter=true'],
        },
        $end_current_url: {
            label: 'Entry URL',
            description: 'The first URL visited in this session.',
            examples: ['https://example.com/interesting-article?parameter=true'],
        },
        $end_pathname: {
            label: 'Entry pathname',
            description: 'The first pathname visited in this session.',
            examples: ['/interesting-article?parameter=true'],
        },
        $exit_current_url: {
            label: 'Exit URL',
            description: 'The last URL visited in this session.',
            examples: ['https://example.com/interesting-article?parameter=true'],
        },
        $exit_pathname: {
            label: 'Exit pathname',
            description: 'The last pathname visited in this session.',
            examples: ['https://example.com/interesting-article?parameter=true'],
        },
        $pageview_count: {
            label: 'Pageview count',
            description: 'The number of page view events in this session.',
            examples: ['123'],
        },
        $autocapture_count: {
            label: 'Autocapture count',
            description: 'The number of autocapture events in this session.',
            examples: ['123'],
        },
        $screen_count: {
            label: 'Screen count',
            description: 'The number of screen events in this session.',
            examples: ['123'],
        },
        $channel_type: {
            label: 'Channel type',
            description: 'What type of acquisition channel this traffic came from.',
            examples: ['Paid Search', 'Organic Video', 'Direct'],
        },
        $is_bounce: {
            label: 'Is bounce',
            description: 'Whether the session was a bounce.',
            examples: ['true', 'false'],
        },
        $last_external_click_url: {
            label: 'Last external click URL',
            description: 'The last external URL clicked in this session.',
            examples: ['https://example.com/interesting-article?parameter=true'],
        },
        $vitals_lcp: {
            label: 'Web vitals LCP',
            description: (
                <span>
                    The time it took for the Largest Contentful Paint on the page. This captures the perceived load time
                    of the page, and measure how long it took for the main content of the page to be visible to users.
                </span>
            ),
            examples: ['2.2'],
        },
    },
    groups: {
        $group_key: {
            label: 'Group Key',
            description: 'Specified group key',
        },
    },
    replay: {
        snapshot_source: {
            label: 'Platform',
            description: 'Platform the session was recorded on',
            examples: ['web', 'mobile'],
        },
        console_log_level: {
            label: 'Log level',
            description: 'Level of console logs captured',
            examples: ['info', 'warn', 'error'],
        },
        console_log_query: {
            label: 'Console log',
            description: 'Text of console logs captured',
        },
        visited_page: {
            label: 'Visited page',
            description: 'URL a user visited during their session',
        },
        click_count: {
            label: 'Clicks',
            description: 'Number of clicks during the session',
        },
        keypress_count: {
            label: 'Key presses',
            description: 'Number of key presses during the session',
        },
        console_error_count: {
            label: 'Errors',
            description: 'Number of console errors during the session',
        },
    },
    log_entries: {
        level: {
            label: 'Console log level',
            description: 'Level of the ',
            examples: ['info', 'warn', 'error'],
        },
        message: {
            label: 'Console log message',
            description: 'The contents of the log message',
        },
    },
} satisfies Partial<Record<TaxonomicFilterGroupType, Record<string, CoreFilterDefinition>>>

CORE_FILTER_DEFINITIONS_BY_GROUP.numerical_event_properties = CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties
// add distinct_id to event properties before copying to person properties so it exists in person properties as well
CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties.distinct_id = CORE_FILTER_DEFINITIONS_BY_GROUP.metadata.distinct_id

for (const [key, value] of Object.entries(CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties)) {
    if (PERSON_PROPERTIES_ADAPTED_FROM_EVENT.has(key) || key.startsWith('$geoip_')) {
        CORE_FILTER_DEFINITIONS_BY_GROUP.person_properties[key] = {
            ...value,
            label: `Latest ${value.label}`,
            description:
                'description' in value
                    ? `${value.description} Data from the last time this user was seen.`
                    : 'Data from the last time this user was seen.',
        }

        CORE_FILTER_DEFINITIONS_BY_GROUP.person_properties[`$initial_${key.replace(/^\$/, '')}`] = {
            ...value,
            label: `Initial ${value.label}`,
            description:
                'description' in value
                    ? `${value.description} Data from the first time this user was seen.`
                    : 'Data from the first time this user was seen.',
        }
    } else {
        CORE_FILTER_DEFINITIONS_BY_GROUP.person_properties[key] = value
    }
    if (SESSION_INITIAL_PROPERTIES_ADAPTED_FROM_EVENTS.has(key)) {
        CORE_FILTER_DEFINITIONS_BY_GROUP.session_properties[`$entry_${key.replace(/^\$/, '')}`] = {
            ...value,
            label: `Entry ${value.label}`,
            description:
                'description' in value
                    ? `${value.description} Data from the first event in this session.`
                    : 'Data from the first event in this session.',
        }
    }
}

// We treat `$session_duration` as an event property in the context of series `math`, but it's fake in a sense
CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties.$session_duration =
    CORE_FILTER_DEFINITIONS_BY_GROUP.session_properties.$session_duration

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

/** Return whether a given filter key is part of PostHog's core (marked by the PostHog logo). */
export function isCoreFilter(key: string): boolean {
    return Object.values(CORE_FILTER_DEFINITIONS_BY_GROUP).some((mapping) => Object.keys(mapping).includes(key))
}

export type PropertyKey = string | null | undefined

export function getCoreFilterDefinition(
    value: string | PropertyFilterValue | undefined,
    type: TaxonomicFilterGroupType
): CoreFilterDefinition | null {
    if (value == undefined) {
        return null
    }

    value = value.toString()
    const isGroupTaxonomicFilterType = type.startsWith('groups_')
    if (type in CORE_FILTER_DEFINITIONS_BY_GROUP && value in CORE_FILTER_DEFINITIONS_BY_GROUP[type]) {
        return { ...CORE_FILTER_DEFINITIONS_BY_GROUP[type][value] }
    } else if (
        isGroupTaxonomicFilterType &&
        value in CORE_FILTER_DEFINITIONS_BY_GROUP[TaxonomicFilterGroupType.GroupsPrefix]
    ) {
        return { ...CORE_FILTER_DEFINITIONS_BY_GROUP[TaxonomicFilterGroupType.GroupsPrefix][value] }
    } else if (value.startsWith('$survey_responded/')) {
        const surveyId = value.replace(/^\$survey_responded\//, '')
        if (surveyId) {
            return {
                label: `Survey Responded: ${surveyId}`,
                description: `Whether the user responded to survey with ID: "${surveyId}".`,
            }
        }
    } else if (value.startsWith('$survey_dismissed/')) {
        const surveyId = value.replace(/^\$survey_dismissed\//, '')
        if (surveyId) {
            return {
                label: `Survey Dismissed: ${surveyId}`,
                description: `Whether the user dismissed survey with ID: "${surveyId}".`,
            }
        }
    } else if (value.startsWith('$survey_response_')) {
        const surveyIndex = value.replace(/^\$survey_response_/, '')
        if (surveyIndex) {
            const index = Number(surveyIndex) + 1
            // yes this will return 21th, but I'm applying the domain logic of
            // it being very unlikely that someone will have more than 20 questions,
            // rather than hyper optimising the suffix.
            const suffix = index === 1 ? 'st' : index === 2 ? 'nd' : index === 3 ? 'rd' : 'th'
            return {
                label: `Survey Response Question ID: ${surveyIndex}`,
                description: `The response value for the ${index}${suffix} question in the survey.`,
            }
        }
    } else if (value.startsWith('$feature/')) {
        const featureFlagKey = value.replace(/^\$feature\//, '')
        if (featureFlagKey) {
            return {
                label: `Feature: ${featureFlagKey}`,
                description: `Value for the feature flag "${featureFlagKey}" when this event was sent.`,
                examples: ['true', 'variant-1a'],
            }
        }
    } else if (value.startsWith('$feature_enrollment/')) {
        const featureFlagKey = value.replace(/^\$feature_enrollment\//, '')
        if (featureFlagKey) {
            return {
                label: `Feature Enrollment: ${featureFlagKey}`,
                description: `Whether the user has opted into the "${featureFlagKey}" beta program.`,
                examples: ['true', 'false'],
            }
        }
    } else if (value.startsWith('$feature_interaction/')) {
        const featureFlagKey = value.replace(/^\$feature_interaction\//, '')
        if (featureFlagKey) {
            return {
                label: `Feature Interaction: ${featureFlagKey}`,
                description: `Whether the user has interacted with "${featureFlagKey}".`,
                examples: ['true', 'false'],
            }
        }
    }
    return null
}

export function getFilterLabel(key: PropertyKey, type: TaxonomicFilterGroupType): string {
    const data = getCoreFilterDefinition(key, type)
    return (data ? data.label : key)?.trim() ?? '(empty string)'
}
