import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'alpha',
    free: false,
    type: 'destination',
    id: 'template-beehiiv',
    name: 'beehiiv',
    description: 'Sync PostHog persons to beehiiv as subscribers',
    icon_url: '/static/services/beehiiv.png',
    category: ['User Engagement Platforms'],
    code_language: 'hog',
    code: `
if (empty(inputs.email)) {
    print('No email set. Skipping...')
    return
}

let headers := {
    'Authorization': f'Bearer {inputs.apiKey}',
    'Content-Type': 'application/json'
}

let customFields := []
for (let name, value in inputs.customFields) {
    if (not empty(name) and not empty(value)) {
        customFields := arrayPushBack(customFields, {
            'name': name,
            'value': value
        })
    }
}

let encodedEmail := encodeURLComponent(inputs.email)
let subscriptionUrl := f'https://api.beehiiv.com/v2/publications/{inputs.publicationId}/subscriptions/by_email/{encodedEmail}'
let getRes := fetch(subscriptionUrl, {
    'method': 'GET',
    'headers': headers
})

if (getRes.status == 404) {
    let createBody := {
        'email': inputs.email,
        'reactivate_existing': inputs.reactivateExisting,
        'send_welcome_email': inputs.sendWelcomeEmail
    }

    if (not empty(inputs.utmSource)) createBody.utm_source := inputs.utmSource
    if (not empty(inputs.utmMedium)) createBody.utm_medium := inputs.utmMedium
    if (not empty(inputs.utmCampaign)) createBody.utm_campaign := inputs.utmCampaign
    if (not empty(inputs.utmTerm)) createBody.utm_term := inputs.utmTerm
    if (not empty(inputs.utmContent)) createBody.utm_content := inputs.utmContent
    if (not empty(inputs.referringSite)) createBody.referring_site := inputs.referringSite
    if (not empty(customFields)) createBody.custom_fields := customFields

    let createRes := fetch(f'https://api.beehiiv.com/v2/publications/{inputs.publicationId}/subscriptions', {
        'method': 'POST',
        'headers': headers,
        'body': createBody
    })

    if (createRes.status >= 400) {
        throw Error(f'Error creating beehiiv subscription (status {createRes.status}): {createRes.body}')
    }

    print(f'Successfully created beehiiv subscription {inputs.email}')
    return
}

if (getRes.status >= 400) {
    throw Error(f'Error looking up beehiiv subscription (status {getRes.status}): {getRes.body}')
}

let updateBody := {}
if (not empty(customFields)) updateBody.custom_fields := customFields
if (inputs.reactivateExisting) updateBody.unsubscribe := false

if (empty(updateBody)) {
    print('Subscription already exists and there are no fields to update. Skipping...')
    return
}

let updateRes := fetch(subscriptionUrl, {
    'method': 'PUT',
    'headers': headers,
    'body': updateBody
})

if (updateRes.status >= 400) {
    throw Error(f'Error updating beehiiv subscription (status {updateRes.status}): {updateRes.body}')
}

print(f'Successfully updated beehiiv subscription {inputs.email}')
`,
    inputs_schema: [
        {
            key: 'apiKey',
            type: 'string',
            label: 'API key',
            description:
                'Create an API key in beehiiv under Settings > Workspace Settings > API. The key must have access to the selected publication.',
            secret: true,
            required: true,
        },
        {
            key: 'publicationId',
            type: 'string',
            label: 'Publication ID',
            description: 'The beehiiv publication ID, beginning with `pub_`.',
            secret: false,
            required: true,
        },
        {
            key: 'email',
            type: 'string',
            label: 'Email',
            description: 'Email address used to find, create, or update the beehiiv subscription.',
            default: '{person.properties.email ?? event.properties.email}',
            secret: false,
            required: true,
        },
        {
            key: 'customFields',
            type: 'dictionary',
            label: 'Custom field mapping',
            description:
                'Map existing beehiiv custom field names to PostHog values. Unknown beehiiv custom fields are ignored by the beehiiv API.',
            default: {
                'First Name': '{person.properties.first_name}',
                'Last Name': '{person.properties.last_name}',
            },
            secret: false,
            required: false,
        },
        {
            key: 'sendWelcomeEmail',
            type: 'boolean',
            label: 'Send welcome email',
            description: 'Send the publication welcome email when a new subscription is created.',
            default: false,
            secret: false,
            required: false,
        },
        {
            key: 'reactivateExisting',
            type: 'boolean',
            label: 'Reactivate existing subscription',
            description:
                'Reactivate a previously unsubscribed subscriber. Enable this only when the person has knowingly requested to resubscribe.',
            default: false,
            secret: false,
            required: false,
        },
        {
            key: 'utmSource',
            type: 'string',
            label: 'UTM source',
            description: 'Acquisition source applied when a subscription is first created.',
            default: 'posthog',
            secret: false,
            required: false,
        },
        {
            key: 'utmMedium',
            type: 'string',
            label: 'UTM medium',
            description: 'Acquisition medium applied when a subscription is first created.',
            default: '{event.properties.utm_medium}',
            secret: false,
            required: false,
        },
        {
            key: 'utmCampaign',
            type: 'string',
            label: 'UTM campaign',
            description: 'Acquisition campaign applied when a subscription is first created.',
            default: '{event.properties.utm_campaign}',
            secret: false,
            required: false,
        },
        {
            key: 'utmTerm',
            type: 'string',
            label: 'UTM term',
            description: 'Acquisition term applied when a subscription is first created.',
            default: '{event.properties.utm_term}',
            secret: false,
            required: false,
        },
        {
            key: 'utmContent',
            type: 'string',
            label: 'UTM content',
            description: 'Acquisition content applied when a subscription is first created.',
            default: '{event.properties.utm_content}',
            secret: false,
            required: false,
        },
        {
            key: 'referringSite',
            type: 'string',
            label: 'Referring site',
            description: 'Referring URL applied when a subscription is first created.',
            default: '{event.properties.$referrer}',
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
