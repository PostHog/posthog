import { HogFunctionInputSchemaType, HogFunctionTemplate } from '~/cdp/types'

// Based on https://developers.openai.com/ads/conversions-api
// Sends server-to-server conversion events to the OpenAI Ads Conversions API.

// Each standard event type must be sent with a matching `data` shape
const EVENT_TYPES: { value: string; label: string; dataType: string }[] = [
    { value: 'app_installed', label: 'App installed', dataType: 'customer_action' },
    { value: 'app_opened', label: 'App opened', dataType: 'customer_action' },
    { value: 'appointment_scheduled', label: 'Appointment scheduled', dataType: 'customer_action' },
    { value: 'checkout_started', label: 'Checkout started', dataType: 'contents' },
    { value: 'contents_viewed', label: 'Contents viewed', dataType: 'contents' },
    { value: 'custom', label: 'Custom', dataType: 'custom' },
    { value: 'items_added', label: 'Items added', dataType: 'contents' },
    { value: 'lead_created', label: 'Lead created', dataType: 'customer_action' },
    { value: 'order_created', label: 'Order created', dataType: 'contents' },
    { value: 'page_viewed', label: 'Page viewed', dataType: 'contents' },
    { value: 'registration_completed', label: 'Registration completed', dataType: 'customer_action' },
    { value: 'subscription_created', label: 'Subscription created', dataType: 'plan_enrollment' },
    { value: 'trial_started', label: 'Trial started', dataType: 'plan_enrollment' },
]

const DATA_TYPE_BY_EVENT_TYPE = EVENT_TYPES.map((e) => `'${e.value}': '${e.dataType}'`).join(', ')

// PostHog events with a default mapping to an OpenAI standard event type. The other
// standard types (lead_created, trial_started, ...) have no standard PostHog
// counterpart, so users map those themselves via the event type choice.
const DEFAULT_MAPPINGS: {
    name: string
    eventType: string
    actionSource?: string
    filterEvent: { id: string; name?: string }
}[] = [
    { name: 'Page viewed', eventType: 'page_viewed', filterEvent: { id: '$pageview', name: 'Pageview' } },
    { name: 'Order created', eventType: 'order_created', filterEvent: { id: 'Order Completed' } },
    { name: 'Checkout started', eventType: 'checkout_started', filterEvent: { id: 'Checkout Started' } },
    { name: 'Items added', eventType: 'items_added', filterEvent: { id: 'Product Added' } },
    { name: 'Contents viewed', eventType: 'contents_viewed', filterEvent: { id: 'Product Viewed' } },
    { name: 'Registration completed', eventType: 'registration_completed', filterEvent: { id: 'Signed Up' } },
    {
        name: 'App installed',
        eventType: 'app_installed',
        actionSource: 'mobile_app',
        filterEvent: { id: 'Application Installed' },
    },
    {
        name: 'App opened',
        eventType: 'app_opened',
        actionSource: 'mobile_app',
        filterEvent: { id: 'Application Opened' },
    },
]

const build_inputs = (defaults: { eventType?: string; actionSource?: string } = {}): HogFunctionInputSchemaType[] => {
    return [
        {
            key: 'eventType',
            type: 'choice',
            label: 'Event type',
            description:
                'The OpenAI standard event type this conversion maps to. Pick "Custom" to send a custom conversion event.',
            default: defaults.eventType ?? 'custom',
            choices: EVENT_TYPES.map(({ value, label }) => ({ value, label })),
            secret: false,
            required: true,
        },
        {
            key: 'customEventName',
            type: 'string',
            label: 'Custom event name',
            description:
                'The event name sent when the event type is "Custom". Spaces are replaced with dashes and uppercase letters are lowercased. The result must be 1-64 characters of lowercase letters, numbers, underscores, or dashes, and must match the custom event configured in OpenAI Ads Manager.',
            default: '{event.event}',
            secret: false,
            required: false,
        },
        {
            key: 'eventId',
            type: 'string',
            label: 'Event ID',
            description: 'A unique ID for the event, used for deduplication against events sent by the OpenAI pixel.',
            default: '{event.uuid}',
            secret: false,
            required: true,
        },
        {
            key: 'eventTime',
            type: 'string',
            label: 'Event time',
            description:
                'The time the event occurred, as a UNIX timestamp in milliseconds (UTC). Must be within the last 7 days.',
            default: '{toInt(toUnixTimestamp(event.timestamp) * 1000)}',
            secret: false,
            required: true,
        },
        {
            key: 'actionSource',
            type: 'choice',
            label: 'Action source',
            description:
                'Where the conversion happened. Must be "Mobile app" for the app installed and app opened event types.',
            default: defaults.actionSource ?? 'web',
            choices: [
                { value: 'web', label: 'Web' },
                { value: 'mobile_app', label: 'Mobile app' },
                { value: 'offline', label: 'Offline' },
                { value: 'physical_store', label: 'Physical store' },
                { value: 'phone_call', label: 'Phone call' },
                { value: 'email', label: 'Email' },
                { value: 'other', label: 'Other' },
            ],
            secret: false,
            required: true,
        },
        {
            key: 'sourceUrl',
            type: 'string',
            label: 'Source URL',
            description: 'The URL the conversion happened on. Required when the action source is "Web".',
            default: '{event.properties.$current_url}',
            secret: false,
            required: false,
        },
        {
            key: 'oppref',
            type: 'string',
            label: 'OpenAI click identifier (oppref)',
            description:
                'The privacy-preserving identifier (oppref) OpenAI appends to ad click-through URLs. PostHog does not capture it automatically, so send it as an event or person property yourself. It gives the most accurate attribution, but conversions can also match on the obref cookie, hashed email, or hashed external ID when it is not available.',
            default: '{event.properties.oppref ?? person.properties.oppref ?? person.properties.$initial_oppref}',
            secret: false,
            required: false,
        },
        {
            key: 'obref',
            type: 'string',
            label: 'OpenAI browser identifier (obref)',
            description:
                'The value of the __obref first-party cookie set by the OpenAI pixel, sent unhashed. PostHog does not read the cookie automatically, so send it as a person property yourself. Only send it for users who have consented to measurement.',
            default: '{person.properties.$obref}',
            secret: false,
            required: false,
        },
        {
            key: 'email',
            type: 'string',
            label: 'Email address',
            description:
                'Email address for conversion matching. Sent SHA-256 hashed; leave blank to omit. Normalize (lowercase, trimmed) for best match rates.',
            default: '{person.properties.email}',
            secret: false,
            required: false,
        },
        {
            key: 'externalId',
            type: 'string',
            label: 'External ID',
            description:
                'A stable pseudonymous customer ID for conversion matching. Sent SHA-256 hashed; leave blank to omit. Do not use raw emails or phone numbers here.',
            default: '{person.properties.external_id}',
            secret: false,
            required: false,
        },
        {
            key: 'phone',
            type: 'string',
            label: 'Phone number',
            description:
                'Phone number for conversion matching, sent SHA-256 hashed. It must include the country code, for example +1 415 555 2671 or 0044 20 7946 0000. A number without a country code is left out, because it cannot be matched. A value that is already a SHA-256 hash is sent as is. Leave blank to omit.',
            default: '{person.properties.phone}',
            secret: false,
            required: false,
        },
        {
            key: 'firstName',
            type: 'string',
            label: 'First name',
            description:
                'First name for conversion matching. It is lowercased, spaces and punctuation are removed, and it is sent SHA-256 hashed. Leave blank to omit.',
            default: '{person.properties.first_name}',
            secret: false,
            required: false,
        },
        {
            key: 'lastName',
            type: 'string',
            label: 'Last name',
            description:
                'Last name for conversion matching. It is lowercased, spaces and punctuation are removed, and it is sent SHA-256 hashed. Leave blank to omit.',
            default: '{person.properties.last_name}',
            secret: false,
            required: false,
        },
        {
            key: 'city',
            type: 'string',
            label: 'City',
            description: 'City for conversion matching. OpenAI takes it unhashed. Leave blank to omit.',
            default: '{person.properties.$geoip_city_name}',
            secret: false,
            required: false,
        },
        {
            key: 'region',
            type: 'string',
            label: 'Region',
            description: 'State or region for conversion matching. OpenAI takes it unhashed. Leave blank to omit.',
            default: '{person.properties.$geoip_subdivision_1_name}',
            secret: false,
            required: false,
        },
        {
            key: 'postalCode',
            type: 'string',
            label: 'Postal code',
            description:
                'Postal code for conversion matching. OpenAI takes it unhashed. A value with characters other than letters, numbers, spaces, or hyphens is left out. Leave blank to omit.',
            default: '{person.properties.$geoip_postal_code}',
            secret: false,
            required: false,
        },
        {
            key: 'country',
            type: 'string',
            label: 'Country code',
            description:
                'Two-letter ISO country code for conversion matching, for example US. OpenAI takes it unhashed. Any other value is left out. Leave blank to omit.',
            default: '{person.properties.$geoip_country_code}',
            secret: false,
            required: false,
        },
        {
            key: 'ipAddress',
            type: 'string',
            label: 'IP address',
            description: 'The IP address of the user, used to improve conversion matching.',
            default: '{event.properties.$ip}',
            secret: false,
            required: false,
        },
        {
            key: 'userAgent',
            type: 'string',
            label: 'User agent',
            description: 'The user agent of the browser the conversion happened in.',
            default: '{event.properties.$raw_user_agent}',
            secret: false,
            required: false,
        },
        {
            key: 'amount',
            type: 'string',
            label: 'Amount (minor currency units)',
            description:
                'The monetary value of the conversion as an integer in ISO 4217 minor units, e.g. 2599 for $25.99. Note this differs from most PostHog revenue properties, which are in major units.',
            default: '',
            secret: false,
            required: false,
        },
        {
            key: 'currency',
            type: 'string',
            label: 'Currency code',
            description:
                'Currency of the amount as an ISO 4217 3-character code, e.g. USD, EUR. Required by OpenAI whenever an amount is sent.',
            default: '',
            secret: false,
            required: false,
        },
    ]
}

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'destination',
    id: 'template-openai-ads',
    name: 'OpenAI Ads Conversions',
    description: 'Send conversion events to the OpenAI Ads Conversions API to measure ads shown in ChatGPT',
    icon_url: '/static/services/openai_ads.svg',
    category: ['Advertisement'],
    code_language: 'hog',
    code: `
// A value that is already a SHA-256 hash is sent as is, so a mapping that hashes upstream is not hashed twice
fn existingSha256(value) {
    let lowered := lower(trim(toString(value)))
    return match(lowered, '^[a-f0-9]{64}$') ? lowered : null
}

// Removes every whitespace character, not only the ASCII space, because OpenAI hashes phones as digits only and names without whitespace
fn removeWhitespace(value) {
    return arrayStringConcat(arrayFilter(character -> not match(character, '[\\t\\n\\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]'), splitByString('', value)), '')
}

// OpenAI hashes the digits only: the country code without the leading + or 00. A number without
// a country code is dropped, because guessing the country would send a hash that matches the wrong person or nobody.
fn hashPhone(value) {
    let phone := removeWhitespace(toString(value))
    for (let separator in ['-', '.', '(', ')']) {
        phone := replaceAll(phone, separator, '')
    }
    if (startsWith(phone, '+')) {
        phone := substring(phone, 2)
    } else if (startsWith(phone, '00')) {
        phone := substring(phone, 3)
    } else {
        return null
    }
    if (not match(phone, '^[1-9][0-9]{7,14}$')) {
        return null
    }
    return sha256Hex(phone)
}

// OpenAI removes all whitespace and ASCII punctuation from names, and keeps accents and other non-ASCII characters
fn hashName(value) {
    let name := removeWhitespace(lower(toString(value)))
    // Most names have no ASCII punctuation, and one match is cheaper than 32 replaceAll calls
    if (not match(name, '[!-/:-@[-\`{-~]')) {
        return empty(name) ? null : sha256Hex(name)
    }
    for (let character in splitByString('', '!"#$%&\\'()*+,-./:;<=>?@[\\\\]^_\`{|}~')) {
        name := replaceAll(name, character, '')
    }
    return empty(name) ? null : sha256Hex(name)
}

// Sets userData[key] to a one-item list with the hash, and returns false when nothing could be hashed
fn setHashed(userData, key, value, hasher) {
    if (empty(value)) {
        return false
    }
    let hash := existingSha256(value) ?? hasher(value)
    if (empty(hash)) {
        return false
    }
    userData[key] := [hash]
    return true
}

let userData := {}
if (not empty(inputs.obref)) {
    userData.obref := inputs.obref
}
setHashed(userData, 'emails_sha256', inputs.email, email -> sha256Hex(lower(trim(toString(email)))))
// An external ID is always hashed, even when it looks like a hash, because a user ID can itself be a hex string
if (not empty(inputs.externalId)) {
    userData.external_ids_sha256 := [sha256Hex(trim(toString(inputs.externalId)))]
}
if (not empty(inputs.phone) and not setHashed(userData, 'phone_numbers_sha256', inputs.phone, hashPhone)) {
    print('\`phone\` has no country code or is not a valid phone number. Sending the conversion without it.')
}
// OpenAI can only attribute a conversion that carries at least one strong identifier;
// IP address, user agent, name and location alone are not enough
if (empty(inputs.oppref) and length(keys(userData)) == 0) {
    print('No \`oppref\`, \`obref\`, \`email\`, \`externalId\` or \`phone\` to identify the user with. Skipping...')
    return
}
if (not empty(inputs.ipAddress)) {
    userData.ip_address := inputs.ipAddress
}
if (not empty(inputs.userAgent)) {
    userData.user_agent := inputs.userAgent
}
setHashed(userData, 'first_names_sha256', inputs.firstName, hashName)
setHashed(userData, 'last_names_sha256', inputs.lastName, hashName)
// OpenAI rejects the whole request when a city or region is longer than 128 characters
if (not empty(inputs.city) and length(trim(toString(inputs.city))) <= 128) {
    userData.cities := [trim(toString(inputs.city))]
}
if (not empty(inputs.region) and length(trim(toString(inputs.region))) <= 128) {
    userData.regions := [trim(toString(inputs.region))]
}
if (not empty(inputs.postalCode)) {
    let postalCode := trim(toString(inputs.postalCode))
    if (match(postalCode, '^[A-Za-z0-9 -]{1,32}$')) {
        userData.postal_codes := [postalCode]
    }
}
if (not empty(inputs.country)) {
    let country := upper(trim(toString(inputs.country)))
    if (match(country, '^[A-Z]{2}$')) {
        userData.countries := [country]
    }
}

let conversion := {
    'id': inputs.eventId,
    'type': inputs.eventType,
    'timestamp_ms': toInt(inputs.eventTime),
    'action_source': inputs.actionSource
}
if (inputs.eventType == 'custom') {
    if (empty(inputs.customEventName)) {
        throw Error('\`customEventName\` is required when the event type is \`custom\`')
    }
    // OpenAI only accepts [a-z0-9_-]{1,64}; normalize the common offenders (spaces, capitals)
    // so the {event.event} default works for typical PostHog event names
    let customEventName := lower(replaceAll(trim(inputs.customEventName), ' ', '-'))
    if (not match(customEventName, '^[a-z0-9_-]{1,64}$')) {
        throw Error(f'\`customEventName\` \`{customEventName}\` is invalid: it must be 1-64 characters of lowercase letters, numbers, underscores, or dashes')
    }
    conversion.custom_event_name := customEventName
}
if ((inputs.eventType == 'app_installed' or inputs.eventType == 'app_opened') and inputs.actionSource != 'mobile_app') {
    throw Error(f'\`actionSource\` must be \`mobile_app\` when the event type is \`{inputs.eventType}\`')
}
if (empty(inputs.sourceUrl)) {
    if (inputs.actionSource == 'web') {
        throw Error('\`sourceUrl\` is required when the action source is \`web\`')
    }
} else {
    conversion.source_url := inputs.sourceUrl
}
if (not empty(inputs.oppref)) {
    conversion.oppref := inputs.oppref
}
if (length(keys(userData)) > 0) {
    conversion.user := userData
}

let dataTypeByEventType := {${DATA_TYPE_BY_EVENT_TYPE}}
let data := {
    'type': dataTypeByEventType[inputs.eventType]
}
if (not empty(inputs.amount)) {
    if (empty(inputs.currency)) {
        print('\`amount\` is set but \`currency\` is missing. Skipping both, as OpenAI requires a currency with every amount.')
    } else {
        data.amount := toInt(inputs.amount)
        data.currency := inputs.currency
    }
}
conversion.data := data

let res := fetch(f'https://bzr.openai.com/v1/events?pid={inputs.pixelId}', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.apiKey}',
        'Content-Type': 'application/json'
    },
    'body': {
        'integration_source': 'posthog',
        'events': [conversion]
    }
})

if (res.status >= 400) {
    throw Error(f'Error from bzr.openai.com (status {res.status}): {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'pixelId',
            type: 'string',
            label: 'Pixel ID',
            description:
                'The ID of the OpenAI pixel that conversions are sent to. Find it in the conversions tab in OpenAI Ads Manager.',
            secret: false,
            required: true,
        },
        {
            key: 'apiKey',
            type: 'string',
            label: 'Conversions API key',
            description: 'The Conversions API key for your pixel, from the conversions tab in OpenAI Ads Manager.',
            secret: true,
            required: true,
        },
    ],
    mapping_templates: [
        ...DEFAULT_MAPPINGS.map(({ name, eventType, actionSource, filterEvent }) => ({
            name,
            include_by_default: true,
            filters: {
                events: [{ ...filterEvent, type: 'events' as const }],
            },
            inputs_schema: build_inputs({ eventType, actionSource }),
        })),
        {
            name: 'Custom',
            include_by_default: false,
            filters: {
                events: [],
            },
            inputs_schema: build_inputs(),
        },
    ],
}
