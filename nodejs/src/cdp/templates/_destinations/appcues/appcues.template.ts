import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'beta',
    free: true,
    type: 'destination',
    id: 'template-appcues',
    name: 'Appcues',
    description:
        'Forward PostHog events and person properties to Appcues to power onboarding flows, in-app messages, and targeting.',
    icon_url: '/static/services/appcues.png',
    category: ['User Engagement Platforms'],
    code_language: 'hog',
    code: `
let userId := inputs.userId
if (empty(userId)) {
    print('No user ID set. Skipping as a user ID is required.')
    return
}

let baseUrl := 'https://api.appcues.com'
if (inputs.region == 'EU') {
    baseUrl := 'https://api.eu.appcues.com'
}

let credentials := base64Encode(f'{inputs.apiKey}:{inputs.apiSecret}')
let headers := {
    'Content-Type': 'application/json',
    'Authorization': f'Basic {credentials}'
}

if (event.event in ('$identify', '$set')) {
    // Identify -> update the Appcues user profile
    let profile := {}
    if (inputs.include_all_properties) {
        for (let key, value in person.properties) {
            if (not key like '$%') {
                profile[key] := value
            }
        }
    }
    for (let key, value in inputs.profileProperties) {
        if (not empty(value)) {
            profile[key] := value
        }
    }

    if (empty(profile)) {
        print('No profile properties to send. Skipping.')
        return
    }

    let res := fetch(f'{baseUrl}/v2/accounts/{inputs.accountId}/users/{userId}/profile', {
        'method': 'PATCH',
        'headers': headers,
        'body': profile
    })

    if (res.status >= 400) {
        throw Error(f'Error from Appcues API (status {res.status}): {res.body}')
    }
} else {
    // Track -> record a user event
    let body := {
        'name': inputs.eventName,
        'timestamp': event.timestamp
    }

    if (not empty(inputs.groupId)) {
        body['group_id'] := inputs.groupId
    }

    let attributes := {}
    if (inputs.include_all_properties) {
        for (let key, value in event.properties) {
            if (not key like '$%') {
                attributes[key] := value
            }
        }
    }
    for (let key, value in inputs.attributes) {
        if (not empty(value)) {
            attributes[key] := value
        }
    }
    if (not empty(attributes)) {
        body['attributes'] := attributes
    }

    let res := fetch(f'{baseUrl}/v2/accounts/{inputs.accountId}/users/{userId}/events', {
        'method': 'POST',
        'headers': headers,
        'body': body
    })

    if (res.status >= 400) {
        throw Error(f'Error from Appcues API (status {res.status}): {res.body}')
    }
}
`,
    inputs_schema: [
        {
            key: 'accountId',
            type: 'string',
            label: 'Account ID',
            description: 'Your numeric Appcues account ID, found on your Appcues account settings page.',
            secret: false,
            required: true,
        },
        {
            key: 'apiKey',
            type: 'string',
            label: 'API Key',
            description: 'Your Appcues API key. Create one under settings in Appcues Studio (studio.appcues.com).',
            secret: true,
            required: true,
        },
        {
            key: 'apiSecret',
            type: 'string',
            label: 'API Secret',
            description: 'The API secret paired with your API key from Appcues Studio.',
            secret: true,
            required: true,
        },
        {
            key: 'region',
            type: 'choice',
            label: 'Data region',
            description: 'The Appcues data region for your account.',
            default: 'US',
            choices: [
                { label: 'US', value: 'US' },
                { label: 'EU', value: 'EU' },
            ],
            secret: false,
            required: true,
        },
        {
            key: 'userId',
            type: 'string',
            label: 'User ID',
            description: 'The identifier for the user in Appcues. Defaults to the PostHog distinct ID.',
            default: '{event.distinct_id}',
            secret: false,
            required: true,
        },
        {
            key: 'include_all_properties',
            type: 'boolean',
            label: 'Include all properties',
            description:
                'If set, all person properties are sent as profile attributes on identify, and all event properties are sent as attributes on track. Internal properties prefixed with $ are excluded. May cause timeouts for persons with many properties.',
            default: false,
            secret: false,
            required: true,
        },
    ],
    filters: {
        events: [],
        actions: [],
        filter_test_accounts: true,
    },
    mapping_templates: [
        {
            name: 'Track Calls',
            include_by_default: true,
            filters: {
                events: [
                    {
                        id: null,
                        name: 'All events',
                        type: 'events',
                        properties: [
                            {
                                key: "event not in ('$identify', '$set', '$groupidentify')",
                                type: 'hogql',
                            },
                        ],
                    },
                ],
            },
            inputs_schema: [
                {
                    key: 'eventName',
                    type: 'string',
                    label: 'Event name',
                    description: 'The name of the event to send to Appcues.',
                    default: '{event.event}',
                    secret: false,
                    required: true,
                },
                {
                    key: 'groupId',
                    type: 'string',
                    label: 'Group ID',
                    description: 'Optional group/account identifier to associate the event with.',
                    default: '',
                    secret: false,
                    required: false,
                },
                {
                    key: 'attributes',
                    type: 'dictionary',
                    label: 'Event attributes',
                    description: 'Map of attribute names to values sent with the event.',
                    default: {},
                    secret: false,
                    required: false,
                },
            ],
        },
        {
            name: 'Identify Calls',
            include_by_default: true,
            filters: {
                events: [
                    {
                        id: null,
                        name: 'All events',
                        type: 'events',
                        properties: [
                            {
                                key: "event in ('$identify', '$set')",
                                type: 'hogql',
                            },
                        ],
                    },
                ],
            },
            inputs_schema: [
                {
                    key: 'profileProperties',
                    type: 'dictionary',
                    label: 'Profile properties',
                    description: 'Map of Appcues profile attribute names to values. Sent on identify events.',
                    default: {
                        email: '{person.properties.email}',
                        first_name: '{person.properties.first_name}',
                        last_name: '{person.properties.last_name}',
                    },
                    secret: false,
                    required: false,
                },
            ],
        },
    ],
}
