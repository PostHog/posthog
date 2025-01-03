import { HogFunctionTemplate } from '../../helpers'

export const template: HogFunctionTemplate = {
    status: 'beta',
    type: 'destination',
    id: 'template-braze',
    name: 'Braze',
    description: 'Send events to Braze',
    icon_url: '/static/services/braze.png',
    category: ['Customer Success'],
    hog: `
if (empty(inputs.api_key)) {
    print('No API key set. Skipping...')
    return
}

if (empty(inputs.external_id) and empty(inputs.email)) {
    print('No external_id or email set. Skipping...')
    return
}

let body := {
    'events': [{
        'name': event.event,
        'time': event.timestamp,
        'properties': event.properties
    }]
}

if (not empty(inputs.external_id)) {
    body['external_id'] := inputs.external_id
}

if (not empty(inputs.email)) {
    body['email'] := inputs.email
}

let res := fetch(f'https://{inputs.instance}/users/track', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.api_key}',
        'Content-Type': 'application/json'
    },
    'body': body
})

if (res.status >= 400) {
    throw Error(f'Error from Braze (status {res.status}): {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'api_key',
            type: 'string',
            label: 'API Key',
            description: 'Your Braze API key',
            secret: true,
            required: true,
        },
        {
            key: 'instance',
            type: 'string',
            label: 'Instance',
            description: 'Your Braze instance (e.g. rest.iad-01.braze.com)',
            secret: false,
            required: true,
        },
        {
            key: 'external_id',
            type: 'string',
            label: 'External ID',
            description: 'The external ID of the user in Braze',
            default: '{person.properties.braze_id}',
            secret: false,
            required: false,
        },
        {
            key: 'email',
            type: 'string',
            label: 'Email',
            description: 'The email of the user in Braze',
            default: '{person.properties.email}',
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
