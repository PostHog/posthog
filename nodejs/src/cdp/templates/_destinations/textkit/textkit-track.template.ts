import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'destination',
    id: 'template-textkit-track',
    name: 'TextKit event',
    description: 'Send events to TextKit to start or advance its SMS automations',
    icon_url: '/static/services/textkit.png',
    category: ['Communication'],
    code_language: 'hog',
    code: `
if (empty(inputs.api_key)) {
    throw Error('API key is required')
}

if (empty(inputs.user_id) and empty(inputs.phone)) {
    throw Error('User ID or phone number is required')
}

// TextKit accepts letters, digits and _ . : - in event names. PostHog names such as
// "$pageview" or "Signed up" would be refused as they stand.
let eventName := replaceAll(replaceAll(trim(inputs.event_name), '$', ''), ' ', '_')

if (empty(eventName)) {
    throw Error('Event name is required')
}

let body := {
    'event': eventName
}

if (not empty(inputs.user_id)) {
    body['user_id'] := inputs.user_id
}

if (not empty(inputs.phone)) {
    body['phone'] := inputs.phone
}

if (not empty(inputs.properties)) {
    body['properties'] := inputs.properties
}

if (inputs.debug) {
    print('Sending event', body)
}

let res := fetch('https://api.jointextkit.com/v1/track', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.api_key}',
        'Content-Type': 'application/json',
        'Idempotency-Key': event.uuid
    },
    'body': body
})

if (res.status < 200 or res.status >= 300) {
    throw Error(f'Failed to send event to TextKit: {res.status}: {res.body.error.message}')
}

if (inputs.debug) {
    print('Event sent', res)
}
`,
    inputs_schema: [
        {
            key: 'api_key',
            type: 'string',
            label: 'API key',
            description: 'A TextKit API key (ssms_sk_...) with the automations scope.',
            secret: true,
            required: true,
        },
        {
            key: 'event_name',
            type: 'string',
            label: 'Event name',
            description: 'Up to 64 characters. A leading $ is dropped and spaces become underscores.',
            default: '{event.event}',
            secret: false,
            required: true,
        },
        {
            key: 'user_id',
            type: 'string',
            label: 'User ID',
            description: 'Your ID for the person. Sent with a phone number, it links the two.',
            default: '{event.distinct_id}',
            secret: false,
            required: false,
        },
        {
            key: 'phone',
            type: 'string',
            label: 'Phone number',
            description: "The person's number in E.164 format, for example +14155550132.",
            default: '{person.properties.phone}',
            secret: false,
            required: false,
        },
        {
            key: 'properties',
            type: 'json',
            label: 'Properties',
            description: 'Up to 20 plain values, usable as merge fields and in conditions in TextKit.',
            default: {
                url: '{event.properties.$current_url}',
            },
            secret: false,
            required: false,
        },
        {
            key: 'debug',
            type: 'boolean',
            label: 'Log responses',
            description: 'Logs the requests and responses for debugging.',
            secret: false,
            required: false,
            default: false,
        },
    ],
}
