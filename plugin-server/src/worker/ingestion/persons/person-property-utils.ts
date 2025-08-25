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
