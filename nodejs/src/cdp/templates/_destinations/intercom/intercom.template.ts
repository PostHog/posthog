import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'stable',
    free: false,
    type: 'destination',
    id: 'template-intercom',
    name: 'Intercom',
    description: 'Update contacts in Intercom',
    icon_url: '/static/services/intercom.png',
    category: [
        'Customer Success',
    ],
    code_language: 'hog',
    code: `
if (empty(inputs.email)) {
    print('No email set. Skipping...')
    return
}

let regions := {
    'US': 'api.intercom.io',
    'Europe': 'api.eu.intercom.io',
    'AU': 'api.au.intercom.io',
}

let user := fetch(f'https://{regions[inputs.oauth['app.region']]}/contacts/search', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
        'Intercom-Version': '2.11',
        'Accept': 'application/json',
        'Authorization': f'Bearer {inputs.oauth.access_token}',
    },
    'body': {
        'query': {
            'field': 'email',
            'operator': '=',
            'value': inputs.email
        }
    }
})

if (user.status >= 400) {
    throw Error(f'Error from intercom api (status {user.status}): {user.body}')
}

let payload := {
    'email': inputs.email,
    'custom_attributes': {}
}

if (inputs.include_all_properties) {
    for (let key, value in person.properties) {
        if (not empty(value) and not key like '$%') {
            payload[key] := value
        }
    }
}

for (let key, value in inputs.properties) {
    if (not empty(value)) {
        payload[key] := value
    }
}

for (let key, value in inputs.customProperties) {
    if (not empty(value)) {
        payload.custom_attributes[key] := value
    }
}

let res

if (user.body.total_count == 1) {
    res := fetch(f'https://{regions[inputs.oauth['app.region']]}/contacts/{user.body.data.1.id}', {
        'method': 'PUT',
        'headers': {
            'Content-Type': 'application/json',
            'Intercom-Version': '2.11',
            'Accept': 'application/json',
            'Authorization': f'Bearer {inputs.oauth.access_token}',
        },
        'body': payload
    })
} else if (user.body.total_count == 0) {
    res := fetch(f'https://{regions[inputs.oauth['app.region']]}/contacts', {
        'method': 'POST',
        'headers': {
            'Content-Type': 'application/json',
            'Intercom-Version': '2.11',
            'Accept': 'application/json',
            'Authorization': f'Bearer {inputs.oauth.access_token}',
        },
        'body': payload
    })
} else {
    throw Error('Found multiple contacts with the same email address. Skipping...')
}

if (res.status >= 400) {
    throw Error(f'Error from intercom api (status {res.status}): {res.body}')
} else if (user.status >= 400) {
    throw Error(f'Error from intercom api (status {user.status}): {user.body}')
}
`.trim(),
    inputs_schema: [
        {
            key: 'oauth',
            type: 'integration',
            integration: 'intercom',
            label: 'Intercom account',
            secret: false,
            required: true,
        },
        {
            key: 'email',
            type: 'string',
            label: 'Email of the user',
            description: 'Where to find the email of the user.',
            default: '{person.properties.email}',
            secret: false,
            required: true,
        },
        {
            key: 'include_all_properties',
            type: 'boolean',
            label: 'Include all properties as attributes',
            description: 'If set, all person properties will be included. Individual attributes can be overridden below.',
            default: false,
            secret: false,
            required: true,
        },
        {
            key: 'properties',
            type: 'dictionary',
            label: 'Default property mapping',
            description: 'Map of Intercom properties and their values.',
            default: {
                name: '{f\'{person.properties.first_name} {person.properties.last_name}\' == \' \' ? null : f\'{person.properties.first_name} {person.properties.last_name}\'}',
                phone: '{person.properties.phone}',
                last_seen_at: '{toUnixTimestamp(event.timestamp)}',
            },
            secret: false,
            required: false,
        },
        {
            key: 'customProperties',
            type: 'dictionary',
            label: 'Custom property mapping',
            description: 'Map of custom properties and their values. Check out this page for more details: https://www.intercom.com/help/en/articles/179-create-and-track-custom-data-attributes-cdas',
            default: {},
            secret: false,
            required: false,
        },
    ],
    filters: {
        events: [
            {
                id: '$identify',
                name: '$identify',
                type: 'events',
                order: 0,
            },
            {
                id: '$set',
                name: '$set',
                type: 'events',
                order: 1,
            },
        ],
        actions: [],
        filter_test_accounts: true,
    },
}
