import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'beta',
    type: 'destination',
    id: 'template-hubspot-company',
    name: 'Hubspot',
    description: 'Creates a new company in Hubspot whenever an event is triggered.',
    icon_url: '/static/services/hubspot.png',
    category: ['CRM', 'Customer Success'],
    code_language: 'hog',
    code: `
let data := {
    'properties': {
        'posthog_group_id': inputs.companyId
    }
}

for (let key, value in inputs.properties) {
    if (typeof(value) in ('object', 'array', 'tuple')) {
        data.properties[key] := jsonStringify(value)
    } else {
        data.properties[key] := value
    }
}

if (empty(data.properties['posthog_group_id'])) {
    print('\`companyId\` input is empty. Skipping...')
    return
}

let headers := {
    'Authorization': f'Bearer {inputs.oauth.access_token}',
    'Content-Type': 'application/json'
}

let res := fetch(f'https://api.hubapi.com/crm/v3/objects/companies/{data.properties['posthog_group_id']}?idProperty=posthog_group_id', {
    'method': 'PATCH',
    'headers': headers,
    'body': data
})

if (res.status == 404) {
    let res2 := fetch('https://api.hubapi.com/crm/v3/properties/companies', {
        'method': 'POST',
        'headers': headers,
        'body': {
            'name': 'posthog_group_id',
            'label': 'PostHog Group ID',
            'description': 'Unique Property to map PostHog Group ID with a HubSpot Company Object',
            'groupName': 'companyinformation',
            'type': 'string',
            'fieldType': 'text',
            'hidden': true,
            'displayOrder': -1,
            'hasUniqueValue': true,
            'formField': false
        }
    })

    if (res2.status >= 400 and not res2.status == 409) {
        throw Error(f'Error creating unique posthog id property (status {res.status}): {res.body}')
    }

    res := fetch('https://api.hubapi.com/crm/v3/objects/companies', {
        'method': 'POST',
        'headers': headers,
        'body': data
    })

    if (res.status >= 400) {
        throw Error(f'Error creating company {data.properties['posthog_group_id']} (status {res.status}): {res.body}')
    } else {
        print(f'Successfully created company {data.properties['posthog_group_id']}')
        return
    }
}

if (res.status >= 400) {
    throw Error(f'Error updating company {data.properties['posthog_group_id']} (status {res.status}): {res.body}')
} else {
    print(f'Successfully updated company {data.properties['posthog_group_id']}')
}
`,
    inputs_schema: [
        {
            key: 'oauth',
            type: 'integration',
            integration: 'hubspot',
            label: 'Hubspot connection',
            requiredScopes: 'crm.objects.companies.write crm.objects.companies.read',
            secret: false,
            required: true,
        },
        {
            key: 'companyId',
            type: 'string',
            label: 'Company ID',
            description: 'A unique identifier that you assign to a company.',
            default: '{groups.company.id}',
            secret: false,
            required: true,
        },
        {
            key: 'properties',
            type: 'dictionary',
            label: 'Property mapping',
            description: 'Map any event properties to Hubspot properties.',
            default: {
                name: '{groups.company.properties.name}',
                domain: '{groups.company.properties.domain}',
                description: '{groups.company.properties.description}',
            },
            secret: false,
            required: true,
        },
    ],
    filters: {
        events: [{ id: '$groupidentify', type: 'events', name: 'Group identify' }],
    },
}
