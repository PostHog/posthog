import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'alpha',
    free: false,
    type: 'destination',
    id: 'template-klime',
    name: 'Klime',
    description: 'Send events to Klime',
    icon_url: '/static/services/klime.png',
    category: ['Analytics'],
    code_language: 'hog',
    code: `
let action := inputs.action

if (action == 'automatic') {
    if (event.event in ('$identify', '$set')) {
        action := 'identify'
    } else if (event.event == '$groupidentify') {
        action := 'group'
    } else {
        action := 'track'
    }
}

let payload := {
    'type': action,
    'messageId': event.uuid,
    'timestamp': event.timestamp
}

if (not empty(inputs.userId)) {
    payload['userId'] := inputs.userId
}

if (action == 'track') {
    payload['event'] := event.event
    if (not empty(inputs.groupId)) {
        payload['groupId'] := inputs.groupId
    }
    let props := {}
    for (let key, value in event.properties) {
        if (not key like '$%') {
            props[key] := value
        }
    }
    for (let key, value in inputs.properties) {
        if (not empty(value)) {
            props[key] := value
        }
    }
    if (not empty(props)) {
        payload['properties'] := props
    }
} else if (action == 'identify') {
    if (empty(inputs.userId)) {
        print('No user ID set. Skipping as user ID is required for identify events.')
        return
    }
    let traits := {}
    if (inputs.include_all_properties) {
        for (let key, value in person.properties) {
            if (not key like '$%') {
                traits[key] := value
            }
        }
    }
    let identifyMapping := inputs.userTraits
    if (empty(identifyMapping)) {
        identifyMapping := inputs.properties
    }
    for (let key, value in identifyMapping) {
        if (not empty(value)) {
            traits[key] := value
        }
    }
    if (not empty(traits)) {
        payload['traits'] := traits
    }
} else if (action == 'group') {
    let gid := inputs.groupId
    if (event.event == '$groupidentify' and not empty(event.properties.$group_key)) {
        gid := event.properties.$group_key
    }
    if (empty(gid)) {
        print('No group ID set. Skipping as group ID is required for group events.')
        return
    }
    payload['groupId'] := gid
    let traits := {}
    let groupSet := event.properties.$group_set
    if (not empty(groupSet)) {
        for (let key, value in groupSet) {
            if (not key like '$%') {
                traits[key] := value
            }
        }
    }
    for (let key, value in inputs.properties) {
        if (not empty(value)) {
            traits[key] := value
        }
    }
    if (not empty(traits)) {
        payload['traits'] := traits
    }
}

payload['context'] := {
    'library': {
        'name': 'posthog-cdp',
        'version': '1.0.0'
    }
}

let res := fetch('https://i.klime.com/v1/batch', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {inputs.writeKey}'
    },
    'body': {
        'batch': [payload]
    }
})

if (res.status >= 400) {
    throw Error(f'Error from Klime API: {res.status}: {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'writeKey',
            type: 'string',
            label: 'Klime Write Key',
            description: 'Your Klime write key for authentication. Find it in your Klime dashboard.',
            default: '',
            secret: true,
            required: true,
        },
        {
            key: 'action',
            type: 'choice',
            label: 'Action',
            description:
                'How to map PostHog events to Klime event types. Automatic converts $identify/$set to identify, $groupidentify to group, and everything else to track.',
            default: 'automatic',
            choices: [
                { label: 'Automatic', value: 'automatic' },
                { label: 'Track', value: 'track' },
                { label: 'Identify', value: 'identify' },
                { label: 'Group', value: 'group' },
            ],
            secret: false,
            required: true,
        },
        {
            key: 'userId',
            type: 'string',
            label: 'User ID',
            description: 'User identifier to send to Klime. Required for identify events.',
            default: '{event.distinct_id}',
            secret: false,
            required: false,
        },
        {
            key: 'groupId',
            type: 'string',
            label: 'Group ID',
            description:
                'Organization or account identifier. Required for group events. Defaults to your first PostHog group type ($group_0). If you use multiple group types, change to $group_1, $group_2, etc. You can also use a custom event property.',
            default: '{event.properties.$group_0}',
            secret: false,
            required: false,
        },
        {
            key: 'include_all_properties',
            type: 'boolean',
            label: 'Include all person properties',
            description:
                'If set, all person properties will be included as traits on identify events. May cause timeouts for persons with many properties.',
            default: false,
            secret: false,
            required: true,
        },
        {
            key: 'userTraits',
            type: 'dictionary',
            label: 'User trait mapping',
            description:
                'Map of trait names to values, sent on identify events. By default sends email and name from person properties.',
            default: { email: '{person.properties.email}', name: '{person.properties.name}' },
            secret: false,
            required: false,
        },
        {
            key: 'properties',
            type: 'dictionary',
            label: 'Property mapping',
            description: 'Map of property names to values. These are sent as properties (track) or traits (group).',
            default: {},
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
