import { HogFunctionTemplate } from '../../helpers'

export const template: HogFunctionTemplate = {
    status: 'beta',
    type: 'destination',
    id: 'template-activecampaign',
    name: 'ActiveCampaign',
    description: 'Create or update contacts in ActiveCampaign',
    icon_url: '/static/services/activecampaign.png',
    category: ['Customer Success'],
    hog: `
if (empty(inputs.email)) {
    print('No email set. Skipping...')
    return
}

let res := fetch(f'https://{inputs.account}.api-us1.com/api/3/contacts', {
    'method': 'POST',
    'headers': {
        'Api-Token': inputs.api_key,
        'Content-Type': 'application/json'
    },
    'body': {
        'contact': {
            'email': inputs.email,
            'firstName': inputs.first_name,
            'lastName': inputs.last_name
        }
    }
})

if (res.status >= 400) {
    throw Error(f'Error from ActiveCampaign (status {res.status}): {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'account',
            type: 'string',
            label: 'Account ID',
            description: 'Your ActiveCampaign account ID (e.g. 123456789)',
            secret: false,
            required: true,
        },
        {
            key: 'api_key',
            type: 'string',
            label: 'API Key',
            description: 'Your ActiveCampaign API key',
            secret: true,
            required: true,
        },
        {
            key: 'email',
            type: 'string',
            label: 'Contact email',
            description: 'The email address of the contact',
            default: '{person.properties.email}',
            secret: false,
            required: true,
        },
        {
            key: 'first_name',
            type: 'string',
            label: 'First name',
            description: 'The first name of the contact',
            default: '{person.properties.first_name}',
            secret: false,
            required: false,
        },
        {
            key: 'last_name',
            type: 'string',
            label: 'Last name',
            description: 'The last name of the contact',
            default: '{person.properties.last_name}',
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
