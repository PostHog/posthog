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
let userData := {}
if (not empty(inputs.obref)) {
    userData.obref := inputs.obref
}
if (not empty(inputs.email)) {
    userData.email_sha256 := sha256Hex(lower(trim(inputs.email)))
}
if (not empty(inputs.externalId)) {
    userData.external_id_sha256 := sha256Hex(trim(inputs.externalId))
}
// OpenAI can only attribute a conversion that carries at least one strong identifier;
// IP address and user agent alone are not enough
if (empty(inputs.oppref) and length(keys(userData)) == 0) {
    print('No \`oppref\`, \`obref\`, \`email\` or \`externalId\` to identify the user with. Skipping...')
    return
}
if (not empty(inputs.ipAddress)) {
    userData.ip_address := inputs.ipAddress
}
if (not empty(inputs.userAgent)) {
    userData.user_agent := inputs.userAgent
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
