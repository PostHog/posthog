import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'alpha',
    free: false,
    type: 'destination',
    id: 'template-unify',
    name: 'Unify',
    description: 'Send PostHog events to Unify',
    icon_url: '/static/services/unify.png',
    category: ['Analytics'],
    code_language: 'hog',
    code: `\
if (empty(inputs.write_key)) {
    throw Error('Unify write key is required.')
}

if (event.event in ('$groupidentify', '$set', '$web_vitals')) {
    print(f'Skipping unsupported event type: {event.event}')
    return
}

let payload := {
    'type': event.event,
    'data': event,
    'person': {
        'email': person.properties.email,
        'properties': person.properties
    },
    'mapping': {
        'person': inputs.person_mapping,
        'company': inputs.company_properties
    }
}

let res := fetch('https://analytics.unifygtm.com/api/v1/webhooks/posthog', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
        'X-Write-Key': inputs.write_key
    },
    'body': payload
})

if (res.status >= 400) {
    throw Error(f'Error from Unify API: {res.status}: {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'write_key',
            type: 'string',
            label: 'Unify Write Key',
            description:
                'Your Unify write key for authentication. You can find your write key in the Unify app under Settings → Integrations → PostHog.',
            default: '',
            secret: true,
            required: true,
        },
        {
            key: 'person_mapping',
            type: 'dictionary',
            label: 'Person',
            description: 'Mapping of Unify Person attributes to PostHog person properties.',
            default: {
                email: '{person.properties.email}',
                first_name: '{person.properties.first_name}',
                last_name: '{person.properties.last_name}',
                title: '{person.properties.title}',
                linkedin_url: '{person.properties.linkedin_url}',
            },
            secret: false,
            required: false,
        },
        {
            key: 'company_properties',
            type: 'dictionary',
            label: 'Company',
            description: 'Mapping of Unify Company attributes to PostHog company properties.',
            default: {
                domain: '',
                name: '',
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
