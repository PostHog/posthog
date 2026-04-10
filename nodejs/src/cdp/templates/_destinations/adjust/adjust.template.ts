import { HogFunctionInputSchemaType } from '~/cdp/types'
import { HogFunctionTemplate } from '~/cdp/types'

const build_inputs = (): HogFunctionInputSchemaType[] => {
    return [
        {
            key: 'eventToken',
            type: 'string',
            label: 'Event token',
            description:
                'The Adjust event token for this event type. Find event tokens in your Adjust dashboard under Events.',
            default: '',
            secret: false,
            required: true,
        },
        {
            key: 'revenue',
            type: 'string',
            label: 'Revenue',
            description: 'Revenue amount for this event (e.g., 29.99 for a purchase).',
            default: '{toFloat(event.properties.revenue ?? event.properties.value ?? event.properties.price)}',
            secret: false,
            required: false,
        },
        {
            key: 'currency',
            type: 'string',
            label: 'Currency',
            description: 'ISO 4217 currency code for revenue (e.g., USD, EUR). Only used when revenue is set.',
            default: '{event.properties.currency}',
            secret: false,
            required: false,
        },
        {
            key: 'callbackParams',
            type: 'dictionary',
            label: 'Callback parameters',
            description:
                'Custom key-value pairs included as callback parameters. These are forwarded to your callback URL configured in Adjust.',
            default: {},
            secret: false,
            required: false,
        },
        {
            key: 'partnerParams',
            type: 'dictionary',
            label: 'Partner parameters',
            description:
                'Custom key-value pairs included as partner parameters. These are forwarded to your configured network partners.',
            default: {},
            secret: false,
            required: false,
        },
    ]
}

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'destination',
    id: 'template-adjust',
    name: 'Adjust',
    description: 'Send events to Adjust for mobile attribution',
    icon_url: '/static/services/adjust.png',
    category: ['Advertisement'],
    code_language: 'hog',
    code: `
if (empty(inputs.appToken)) {
    throw Error('Adjust app token is required')
}

if (empty(inputs.eventToken)) {
    throw Error('Adjust event token is required')
}

let deviceParams := ''
let hasDeviceId := false
for (let key, value in inputs.deviceIdentifiers) {
    if (not empty(value)) {
        deviceParams := f'{deviceParams}&{encodeURLComponent(key)}={encodeURLComponent(value)}'
        hasDeviceId := true
    }
}

if (not hasDeviceId) {
    throw Error('At least one device identifier is required (idfa, gps_adid, android_id, idfv, or adid)')
}

let body := f's2s=1&app_token={encodeURLComponent(inputs.appToken)}&event_token={encodeURLComponent(inputs.eventToken)}&environment={encodeURLComponent(inputs.environment)}'

body := f'{body}{deviceParams}'

if (not empty(inputs.revenue)) {
    body := f'{body}&revenue={encodeURLComponent(toString(inputs.revenue))}'
    if (not empty(inputs.currency)) {
        body := f'{body}&currency={encodeURLComponent(inputs.currency)}'
    }
}

let hasCallbackParams := false
for (let key, value in inputs.callbackParams) {
    if (not empty(value)) {
        hasCallbackParams := true
    }
}
if (hasCallbackParams) {
    body := f'{body}&callback_params={encodeURLComponent(jsonStringify(inputs.callbackParams))}'
}

let hasPartnerParams := false
for (let key, value in inputs.partnerParams) {
    if (not empty(value)) {
        hasPartnerParams := true
    }
}
if (hasPartnerParams) {
    body := f'{body}&partner_params={encodeURLComponent(jsonStringify(inputs.partnerParams))}'
}

if (not empty(event.properties.$ip)) {
    body := f'{body}&ip_address={encodeURLComponent(event.properties.$ip)}'
}

if (not empty(event.properties.$raw_user_agent)) {
    body := f'{body}&user_agent={encodeURLComponent(event.properties.$raw_user_agent)}'
}

body := f'{body}&created_at_unix={toUnixTimestamp(event.timestamp)}'

let res := fetch('https://s2s.adjust.com/event', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/x-www-form-urlencoded'
    },
    'body': body
})
if (res.status >= 400) {
    throw Error(f'Error from s2s.adjust.com (status {res.status}): {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'appToken',
            type: 'string',
            label: 'App token',
            description: 'Your Adjust app token. Find it in the Adjust dashboard under App settings.',
            secret: true,
            required: true,
        },
        {
            key: 'environment',
            type: 'choice',
            label: 'Environment',
            choices: [
                { label: 'Production', value: 'production' },
                { label: 'Sandbox', value: 'sandbox' },
            ],
            description: 'Set to Sandbox for testing, Production for live traffic.',
            default: 'production',
            secret: false,
            required: true,
        },
        {
            key: 'deviceIdentifiers',
            type: 'dictionary',
            label: 'Device identifiers',
            description:
                'Map of device identifiers to send with events. At least one is required. Keys must match Adjust parameter names: idfa (iOS), gps_adid (Android), android_id, idfv, or adid.',
            default: {
                idfa: '{person.properties.$device_idfa}',
                gps_adid: '{person.properties.$android_advertising_id}',
                idfv: '{event.properties.$device_id}',
            },
            secret: false,
            required: true,
        },
    ],
    mapping_templates: [
        {
            name: 'Application Installed',
            include_by_default: true,
            filters: {
                events: [{ id: 'Application Installed', type: 'events' }],
            },
            inputs_schema: [...build_inputs()],
        },
        {
            name: 'Application Opened',
            include_by_default: true,
            filters: {
                events: [{ id: 'Application Opened', type: 'events' }],
            },
            inputs_schema: [...build_inputs()],
        },
        {
            name: 'Signed Up',
            include_by_default: true,
            filters: {
                events: [{ id: 'Signed Up', type: 'events' }],
            },
            inputs_schema: [...build_inputs()],
        },
        {
            name: 'Order Completed',
            include_by_default: true,
            filters: {
                events: [{ id: 'Order Completed', type: 'events' }],
            },
            inputs_schema: [...build_inputs()],
        },
        {
            name: 'Product Added',
            include_by_default: true,
            filters: {
                events: [{ id: 'Product Added', type: 'events' }],
            },
            inputs_schema: [...build_inputs()],
        },
        {
            name: 'Checkout Started',
            include_by_default: true,
            filters: {
                events: [{ id: 'Checkout Started', type: 'events' }],
            },
            inputs_schema: [...build_inputs()],
        },
    ],
}
