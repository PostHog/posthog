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
    code: `
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
    'person': inputs.person_attributes,
    'company': inputs.company_attributes
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
            key: 'person_attributes',
            type: 'dictionary',
            label: 'Person',
            description:
                'Mapping of Unify Person attributes to PostHog person properties. Email is required to associate an event with a Person.',
            default: {
                email: '{person.properties.email}',
                address: '{person.properties.address}',
                corporate_phone: '{person.properties.corporate_phone}',
                do_not_call: '{person.properties.do_not_call}',
                do_not_email: '{person.properties.do_not_email}',
                email_opt_out: '{person.properties.email_opt_out}',
                eu_resident: '{person.properties.eu_resident}',
                first_name: '{person.properties.first_name}',
                last_name: '{person.properties.last_name}',
                lead_source: '{person.properties.lead_source}',
                linkedin_url: '{person.properties.linkedin_url}',
                mobile_phone: '{person.properties.mobile_phone}',
                status: '{person.properties.status}',
                title: '{person.properties.title}',
                work_phone: '{person.properties.work_phone}',
            },
            secret: false,
            required: false,
        },
        {
            key: 'company_attributes',
            type: 'dictionary',
            label: 'Company',
            description:
                'Mapping of Unify Company attributes to PostHog company properties. Domain is required to associate an event with a Company.',
            default: {
                domain: '{groups.company.properties.domain}',
                address: '{groups.company.properties.address}',
                corporate_phone: '{groups.company.properties.corporate_phone}',
                description: '{groups.company.properties.description}',
                do_not_contact: '{groups.company.properties.do_not_contact}',
                employee_count: '{groups.company.properties.employee_count}',
                founded: '{groups.company.properties.founded}',
                industry: '{groups.company.properties.industry}',
                lead_source: '{groups.company.properties.lead_source}',
                linkedin_url: '{groups.company.properties.linkedin_url}',
                name: '{groups.company.properties.name}',
                revenue: '{groups.company.properties.revenue}',
                status: '{groups.company.properties.status}',
                time_zone: '{groups.company.properties.time_zone}',
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
