import { HogFunctionTemplate } from '../../helpers'

export const template: HogFunctionTemplate = {
    status: 'beta',
    type: 'destination',
    id: 'template-gleap',
    name: 'Gleap',
    description: 'Updates a contact in Gleap',
    icon_url: '/static/services/gleap.png',
    category: ['Customer Success'],
    hog: `
if (empty(inputs.userId)) {
    print('No User ID set. Skipping...')
    return
}

let attributes := inputs.include_all_properties ? person.properties : {}

attributes['userId'] := inputs.userId

for (let key, value in inputs.attributes) {
    if (not empty(value)) {
        attributes[key] := value
    }
}

let res := fetch('https://api.gleap.io/admin/identify', {
    'method': 'POST',
    'headers': {
        'User-Agent': 'PostHog Gleap.io App',
        'Api-Token': inputs.apiKey,
        'Content-Type': 'application/json'
    },
    'body': attributes
})

if (res.status >= 400) {
    throw Error(f'Error from gleap.io (status {res.status}): {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'apiKey',
            type: 'string',
            label: 'Gleap.io API Key',
            secret: true,
            required: true,
        },
        {
            key: 'userId',
            type: 'string',
            label: 'User ID',
            description:
                'You can choose to fill this from an `email` property or an `id` property. If the value is empty nothing will be sent. See here for more information: https://docs.gleap.io/server/rest-api',
            default: '{person.id}',
            secret: false,
            required: true,
        },
        {
            key: 'include_all_properties',
            type: 'boolean',
            label: 'Include all properties as attributes',
            description:
                'If set, all person properties will be included as attributes. Individual attributes can be overridden below.',
            default: false,
            secret: false,
            required: true,
        },
        {
            key: 'attributes',
            type: 'dictionary',
            label: 'Attribute mapping',
            description:
                'Map of Gleap.io attributes and their values. You can use the filters section to filter out unwanted events.',
            default: {
                email: '{person.properties.email}',
                name: '{person.properties.name}',
                phone: '{person.properties.phone}',
            },
            secret: false,
            required: false,
        },
    ],
    filters: {
        events: [
            { id: '$identify', name: '$identify', type: 'events', order: 0 },
            { id: '$set', name: '$set', type: 'events', order: 1 },
        ],
        actions: [],
        filter_test_accounts: true,
    },
}
