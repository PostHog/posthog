import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'beta',
    free: false,
    type: 'destination',
    id: 'template-attio',
    name: 'Attio',
    description: 'Create and update contacts in Attio',
    icon_url: '/static/services/attio.png',
    category: ['Advertisement'],
    code_language: 'hog',
    code: `
let body := {
    'data': {
        'values': {
            'email_addresses': [
                {
                    'email_address': inputs.email
                }
            ]
        }
    }
}

for (let key, value in inputs.personAttributes) {
    if (not empty(value)) {
        body.data.values[key] := value
    }
}

let res := fetch(f'https://api.attio.com/v2/objects/people/records?matching_attribute=email_addresses', {
    'method': 'PUT',
    'headers': {
        'Authorization': f'Bearer {inputs.apiKey}',
        'Content-Type': 'application/json',
    },
    'body': body
})
if (res.status >= 400) {
    throw Error(f'Error from api.attio.com (status {res.status}): {res.body}')
}
`.trim(),
    inputs_schema: [
        {
            key: 'apiKey',
            type: 'string',
            label: 'Access token',
            description:
                'Check out this page to get your API key: https://attio.com/help/reference/integrations-automations/generating-an-api-key',
            secret: true,
            required: true,
        },
        {
            key: 'email',
            type: 'string',
            label: 'Email of the user',
            description:
                'Where to find the email for the contact to be created. You can use the filters section to filter out unwanted emails or internal users.',
            default: '{person.properties.email}',
            secret: false,
            required: true,
        },
        {
            key: 'personAttributes',
            type: 'dictionary',
            label: 'Additional Person attributes',
            description:
                'This persons keys should be the slugs or IDs of the attributes you wish to update. For information on potential custom attributes, refer to the attribute type docs: https://developers.attio.com/docs/attribute-types',
            default: {
                name: '{person.properties.name}',
                job_title: '{person.properties.job_title}',
            },
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
