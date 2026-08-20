import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'beta',
    free: true,
    type: 'destination',
    id: 'template-retain',
    name: 'Retain',
    description:
        'Send product usage and identity events to Retain for churn prediction, customer health scoring, and at-risk account alerts.',
    icon_url: '/static/services/retain.png',
    category: ['Analytics'],
    code_language: 'hog',
    code: `
// Retain only consumes product usage and identity events. Skip PostHog
// internal events ($pageview, $autocapture, $feature_flag_called, ...) to
// avoid useless requests — Retain would ignore them anyway.
let allowedSystemEvents := ['$identify', '$set', '$groupidentify']
if (startsWith(event.event, '$') and not (event.event in allowedSystemEvents)) {
    return
}

let res := fetch('https://api.retain.so/sources/posthog', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Basic {inputs.writeKey}',
        'Content-Type': 'application/json'
    },
    'body': {
        'event': {
            'uuid': event.uuid,
            'event': event.event,
            'distinct_id': event.distinct_id,
            'properties': event.properties,
            'timestamp': event.timestamp
        },
        'person': {
            'properties': person.properties
        }
    }
})

if (res.status >= 400) {
    throw Error(f'Error from api.retain.so (status {res.status}): {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'writeKey',
            type: 'string',
            label: 'Retain write key',
            description:
                'Your Retain project write key (starts with "rk-"). Find it in your Retain dashboard under Settings → Project token.',
            secret: true,
            required: true,
        },
    ],
    filters: {
        events: [],
        actions: [],
        filter_test_accounts: true,
    },
}
