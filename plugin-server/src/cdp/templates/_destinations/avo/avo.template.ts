import { HogFunctionTemplate } from '../../helpers'

export const template: HogFunctionTemplate = {
    status: 'beta',
    type: 'destination',
    id: 'template-avo',
    name: 'Avo',
    description: 'Send events to Avo',
    icon_url: '/static/services/avo.png',
    category: ['Analytics'],
    hog: `
if (empty(inputs.api_key)) {
    print('No API key set. Skipping...')
    return
}

let body := {
    'apiKey': inputs.api_key,
    'env': inputs.environment,
    'eventName': event.event,
    'eventProperties': event.properties,
    'systemProperties': {
        'source': 'posthog',
        'sourceVersion': '1.0.0'
    }
}

let res := fetch('https://api.avo.app/track', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json'
    },
    'body': body
})

if (res.status >= 400) {
    throw Error(f'Error from Avo (status {res.status}): {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'api_key',
            type: 'string',
            label: 'API Key',
            description: 'Your Avo API key',
            secret: true,
            required: true,
        },
        {
            key: 'environment',
            type: 'string',
            label: 'Environment',
            description: 'The environment to send events to (e.g. development, production)',
            default: 'production',
            secret: false,
            required: true,
        },
    ],
    filters: {
        events: [],
        actions: [],
        filter_test_accounts: true,
    },
}
