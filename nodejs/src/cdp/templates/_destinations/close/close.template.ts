import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'alpha',
    free: false,
    type: 'destination',
    id: 'template-close',
    name: 'Close',
    description:
        'Sync PostHog persons to Close as contacts. Creates a new lead when no contact with the same email exists yet.',
    icon_url: '/static/services/close.png',
    category: ['CRM', 'Customer Success'],
    code_language: 'hog',
    code: `
if (empty(inputs.email)) {
    print('No email set. Skipping...')
    return
}

let headers := {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'Authorization': f'Basic {base64Encode(f'{inputs.apiKey}:')}',
}

let searchRes := fetch('https://api.close.com/api/v1/data/search/', {
    'method': 'POST',
    'headers': headers,
    'body': {
        'query': {
            'type': 'and',
            'queries': [
                {'type': 'object_type', 'object_type': 'contact'},
                {
                    'type': 'has_related',
                    'this_object_type': 'contact',
                    'related_object_type': 'contact_email',
                    'related_query': {
                        'type': 'field_condition',
                        'field': {'type': 'regular_field', 'object_type': 'contact_email', 'field_name': 'email'},
                        'condition': {'type': 'text', 'mode': 'phrase', 'value': inputs.email}
                    }
                }
            ]
        },
        '_fields': {'contact': ['id', 'lead_id']},
        '_limit': 1
    }
})

if (searchRes.status >= 400) {
    throw Error(f'Error from api.close.com (status {searchRes.status}): {searchRes.body}')
}

let contactAttributes := {}

for (let key, value in inputs.properties) {
    if (not empty(value)) {
        if (typeof(value) in ('object', 'array', 'tuple')) {
            contactAttributes[key] := jsonStringify(value)
        } else {
            contactAttributes[key] := value
        }
    }
}

let fullName := trim(f'{inputs.firstName} {inputs.lastName}')
if (not empty(fullName)) {
    contactAttributes.name := fullName
}

let res

if (not empty(searchRes.body.data)) {
    if (empty(contactAttributes)) {
        print('No contact fields to update. Skipping...')
        return
    }
    // Never send emails on update - PUT replaces the contact's whole emails array
    res := fetch(f'https://api.close.com/api/v1/contact/{searchRes.body.data.1.id}/', {
        'method': 'PUT',
        'headers': headers,
        'body': contactAttributes
    })
} else {
    let contact := {
        'emails': [{'email': inputs.email, 'type': 'office'}]
    }
    for (let key, value in contactAttributes) {
        contact[key] := value
    }
    let lead := {
        'name': inputs.leadName,
        'contacts': [contact]
    }
    for (let key, value in inputs.leadProperties) {
        if (not empty(value)) {
            lead[key] := value
        }
    }
    res := fetch('https://api.close.com/api/v1/lead/', {
        'method': 'POST',
        'headers': headers,
        'body': lead
    })
}

if (res.status >= 400) {
    throw Error(f'Error from api.close.com (status {res.status}): {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'apiKey',
            type: 'string',
            label: 'Close API key',
            description:
                'You can create an API key in Settings > Developer > API keys: https://app.close.com/settings/developer/api-keys/',
            secret: true,
            required: true,
        },
        {
            key: 'email',
            type: 'string',
            label: 'Email of the user',
            description:
                'Where to find the email of the contact. You can use the filters section to filter out unwanted emails or internal users.',
            default: '{person.properties.email}',
            secret: false,
            required: true,
        },
        {
            key: 'leadName',
            type: 'string',
            label: 'Lead name',
            description: 'Name of the lead (company) to create if no contact with this email exists yet.',
            default: '{person.properties.company ?? person.properties.email}',
            secret: false,
            required: true,
        },
        {
            key: 'firstName',
            type: 'string',
            label: 'First name',
            description:
                "First name of the contact. Combined with the last name and sent as Close's single `name` field; if both are empty the name is omitted.",
            default: '{person.properties.first_name}',
            secret: false,
            required: false,
        },
        {
            key: 'lastName',
            type: 'string',
            label: 'Last name',
            description:
                "Last name of the contact. Combined with the first name and sent as Close's single `name` field; if both are empty the name is omitted.",
            default: '{person.properties.last_name}',
            secret: false,
            required: false,
        },
        {
            key: 'properties',
            type: 'dictionary',
            label: 'Contact field mapping',
            description:
                'Map of Close contact fields and their values. Note that Close only accepts valid contact fields (e.g. title, or custom.cf_FIELD_ID keys) - unknown fields may be rejected. Custom fields use the custom.cf_FIELD_ID format: https://developer.close.com/resources/custom-fields/',
            default: {
                title: '{person.properties.job_title}',
            },
            secret: false,
            required: false,
        },
        {
            key: 'leadProperties',
            type: 'dictionary',
            label: 'Lead field mapping',
            description:
                'Map of Close lead fields and their values, only applied when a new lead is created (e.g. url or custom.cf_FIELD_ID keys).',
            default: {},
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
