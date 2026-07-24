import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'destination',
    id: 'template-witn',
    name: 'witn',
    description: 'Send events to witn for outcome tracking and billing condition evaluation',
    icon_url: '/static/services/witn.svg',
    category: ['Customer Data Platforms'],
    code_language: 'hog',
    code: `
if (empty(inputs.key)) {
    throw Error('Key is required')
}

if (empty(inputs.action)) {
    throw Error('Action is required')
}

if (empty(inputs.customer_key)) {
    throw Error('Customer key is required')
}

let body := {
    'key': inputs.key,
    'action': inputs.action,
    'customer_key': inputs.customer_key,
}

if (not empty(inputs.agent_key)) {
    body.agent_key := inputs.agent_key
}

if (not empty(inputs.timestamp)) {
    body.timestamp := inputs.timestamp
}

if (not empty(inputs.idempotency_key)) {
    body.idempotency_key := inputs.idempotency_key
}

let properties := {}
for (let key, value in inputs.properties) {
    if (not empty(value)) {
        properties[key] := value
    }
}

if (not empty(properties)) {
    body.properties := properties
}

let res := fetch(f'{inputs.api_base_url}/v1/events', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.api_key}',
        'Content-Type': 'application/json',
    },
    'body': body
})

if (res.status < 200 or res.status >= 300) {
    throw Error(f'Error from witn API (status {res.status}): {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'api_key',
            type: 'string',
            label: 'API key',
            description: 'Your witn API key.',
            secret: true,
            required: true,
        },
        {
            key: 'api_base_url',
            type: 'string',
            label: 'API base URL',
            description: 'The witn API base URL, without a trailing slash.',
            default: 'https://api.thewitn.com',
            secret: false,
            required: true,
        },
        {
            key: 'key',
            type: 'string',
            label: 'Key',
            description:
                'The witn key. Events with the same key are grouped into one outcome, so use a value that is stable across the outcome (a ticket ID, session ID, or order ID) — not a per-event value. Must be 8-255 characters.',
            default: '{event.properties.key}',
            secret: false,
            required: true,
        },
        {
            key: 'action',
            type: 'string',
            label: 'Action',
            description: 'What happened. This is matched against the witn billable condition.',
            default: '{event.event}',
            secret: false,
            required: true,
        },
        {
            key: 'customer_key',
            type: 'string',
            label: 'Customer key',
            description: "The customer's key in witn.",
            default: '{person.properties.email}',
            secret: false,
            required: true,
        },
        {
            key: 'agent_key',
            type: 'string',
            label: 'Agent key',
            description: 'Optional witn agent key. Omit to let witn infer the agent.',
            default: '',
            secret: false,
            required: false,
        },
        {
            key: 'idempotency_key',
            type: 'string',
            label: 'Idempotency key',
            description:
                'Optional key that makes retries safe: the same key for the same outcome always maps to the same event.',
            default: '{event.uuid}',
            secret: false,
            required: false,
        },
        {
            key: 'timestamp',
            type: 'string',
            label: 'Event timestamp',
            description: 'Optional ISO timestamp for when the event occurred.',
            default: '{event.timestamp}',
            secret: false,
            required: false,
        },
        {
            key: 'properties',
            type: 'dictionary',
            label: 'Properties',
            description:
                'Optional event metadata. witn reserves value, attribution, and settles_at for condition evaluation and billing.',
            default: {
                value: '{event.properties.value}',
                attribution: '{event.properties.attribution}',
                settles_at: '{event.properties.settles_at}',
            },
            secret: false,
            required: false,
        },
    ],
    filters: {
        events: [],
        actions: [],
        filter_test_accounts: true,
    },
}
