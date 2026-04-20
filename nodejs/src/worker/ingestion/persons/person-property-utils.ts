// Core person properties that should be preserved during trimming
const CORE_PERSON_PROPERTIES = new Set(['email', 'name'])

// Properties automatically mapped from events to persons
const EVENT_TO_PERSON_PROPERTIES = new Set([
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
    '$os_name', // $os_name is a special case, it's treated as an alias of $os!
    '$os_version',
    '$referring_domain',
    '$referrer',
    '$screen_height',
    '$screen_width',
    '$viewport_height',
    '$viewport_width',
    '$raw_user_agent',
])

// UTM and campaign tracking properties
// Keep in sync with:
// - taxonomy.tsx (CAMPAIGN_PROPERTIES)
// - posthog-js event-utils.ts (CAMPAIGN_PARAMS)
const CAMPAIGN_PROPERTIES = new Set([
    'utm_source',
    'utm_medium',
    'utm_campaign',
    'utm_content',
    'utm_name',
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
    // Additional campaign params specific to person properties
    'epik',
    'qclid',
    'sccid',
])

// Session and page tracking properties
const SESSION_PROPERTIES = new Set(['$session_id', '$window_id', '$pageview_id', '$host'])

// Identity and device tracking properties
const IDENTITY_PROPERTIES = new Set(['$user_id', '$device_id', '$anon_distinct_id'])

// Initial/first-touch properties
const INITIAL_PROPERTIES = new Set([
    '$initial_referrer',
    '$initial_referring_domain',
    '$initial_utm_source',
    '$initial_utm_medium',
    '$initial_utm_campaign',
    '$initial_utm_content',
    '$initial_utm_term',
])

// Combined set of all properties that should be protected from trimming
const ALL_PROTECTED_PROPERTIES = new Set([
    ...CORE_PERSON_PROPERTIES,
    ...EVENT_TO_PERSON_PROPERTIES,
    ...CAMPAIGN_PROPERTIES,
    ...SESSION_PROPERTIES,
    ...IDENTITY_PROPERTIES,
    ...INITIAL_PROPERTIES,
])

/**
 * Determines if a property can be trimmed during person property size remediation.
 * Protected properties (core, campaign, event-mapped, etc.) should not be trimmed.
 */
export function canTrimProperty(propertyName: string): boolean {
    return !ALL_PROTECTED_PROPERTIES.has(propertyName)
}

/**
 * Determines if a property is a core person property (email, name).
 */
export function isCorePersonProperty(propertyName: string): boolean {
    return CORE_PERSON_PROPERTIES.has(propertyName)
}

/**
 * Determines if a property is automatically mapped from events to persons.
 */
export function isEventToPersonProperty(propertyName: string): boolean {
    return EVENT_TO_PERSON_PROPERTIES.has(propertyName)
}

/**
 * Determines if a property is a campaign/UTM tracking property.
 */
export function isCampaignProperty(propertyName: string): boolean {
    return CAMPAIGN_PROPERTIES.has(propertyName)
}

/**
 * Determines if a property is a session tracking property.
 */
export function isSessionProperty(propertyName: string): boolean {
    return SESSION_PROPERTIES.has(propertyName)
}

/**
 * Determines if a property is an identity tracking property.
 */
export function isIdentityProperty(propertyName: string): boolean {
    return IDENTITY_PROPERTIES.has(propertyName)
}

/**
 * Determines if a property is an initial/first-touch property.
 */
export function isInitialProperty(propertyName: string): boolean {
    return INITIAL_PROPERTIES.has(propertyName)
}

export const eventToPersonProperties = new Set([...EVENT_TO_PERSON_PROPERTIES, ...CAMPAIGN_PROPERTIES])

export const initialCampaignParams = new Set(
    Array.from(CAMPAIGN_PROPERTIES, (key) => `$initial_${key.replace('$', '')}`)
)
export const initialEventToPersonProperties = new Set(
    Array.from(eventToPersonProperties, (key) => `$initial_${key.replace('$', '')}`)
)

/**
 * Properties that should NOT trigger a person update on their own.
 * These change frequently but aren't valuable enough to update the person record for.
 * They will still be included in the person properties when an update happens for other reasons.
 *
 * This is the single source of truth for person update filtering logic.
 *
 * Note: Properties NOT in this list will trigger updates by default.
 *
 * GeoIP properties source: posthog/geoip.py and posthog/taxonomy/taxonomy.py
 * GeoIP properties that DO trigger updates (not listed here): $geoip_country_name, $geoip_city_name
 */
export const FILTERED_PERSON_UPDATE_PROPERTIES = new Set([
    // URL/navigation properties - change on every page view
    '$current_url',
    '$pathname',
    '$referring_domain',
    '$referrer',

    // Screen/viewport dimensions - can change on window resize
    '$screen_height',
    '$screen_width',
    '$viewport_height',
    '$viewport_width',

    // Browser/device properties - change less frequently but still filtered
    '$browser',
    '$browser_version',
    '$device_type',
    '$raw_user_agent',
    '$os',
    '$os_name',
    '$os_version',

    // GeoIP properties - filtered because they change frequently
    '$geoip_postal_code',
    '$geoip_time_zone',
    '$geoip_latitude',
    '$geoip_longitude',
    '$geoip_accuracy_radius',
    '$geoip_subdivision_1_code',
    '$geoip_subdivision_1_name',
    '$geoip_subdivision_2_code',
    '$geoip_subdivision_2_name',
    '$geoip_subdivision_3_code',
    '$geoip_subdivision_3_name',
    '$geoip_city_confidence',
    '$geoip_country_confidence',
    '$geoip_postal_code_confidence',
    '$geoip_subdivision_1_confidence',
    '$geoip_subdivision_2_confidence',
])

/**
 * Determines if a property key should be filtered out from triggering person updates.
 * These are properties that change frequently but aren't valuable enough to update the person record for.
 *
 * This is the single source of truth for property filtering logic, used by both:
 * - Event-level processing (computeEventPropertyUpdates in person-update.ts)
 * - Batch-level processing (getPersonUpdateOutcome in batch-writing-person-store.ts)
 */
export function isFilteredPersonUpdateProperty(key: string): boolean {
    return FILTERED_PERSON_UPDATE_PROPERTIES.has(key)
}
