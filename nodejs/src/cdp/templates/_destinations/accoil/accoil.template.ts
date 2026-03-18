import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'beta',
    free: true,
    type: 'destination',
    id: 'template-accoil',
    name: 'Accoil',
    description:
        'Pipe PostHog data to Accoil for usage-based account scoring, churn alerts, and expansion insights — automatically shared with Customer Success, Sales, RevOps, and Leadership in tools like Slack and HubSpot.',
    icon_url: '/static/services/accoil.com.png',
    category: ['Analytics'],
    code_language: 'hog',
    code: `
// Skip PostHog internal events that start with $ unless they're in our whitelist
let allowedSystemEvents := ['$pageview', '$screen', '$identify', '$set', '$groupidentify']
if (startsWith(event.event, '$') and not (event.event in allowedSystemEvents)) {
    return
}

// Determine the call type based on event
let type := 'track'
if (event.event == '$pageview') {
    type := 'page'
} else if (event.event == '$screen') {
    type := 'screen'
} else if (event.event in ('$identify', '$set')) {
    type := 'identify'
} else if (event.event == '$groupidentify') {
    type := 'group'
}

// Base payload
let body := {
    'type': type,
    'timestamp': toString(inputs.timestamp)
}

// Add userId if provided and not empty
if (not empty(inputs.userId)) {
    body.userId := toString(inputs.userId)
}

// Add anonymousId if provided and not empty
if (not empty(inputs.anonymousId)) {
    body.anonymousId := toString(inputs.anonymousId)
}

// Type-specific fields
if (type == 'track') {
    body.event := toString(inputs.event)
} else if (type == 'page' or type == 'screen') {
    // Return early if we can't parse a page/screen name to avoid sending useless events
    if (empty(inputs.name)) {
        return
    }

    body.name := toString(inputs.name)
} else if (type == 'identify') {
    let traits := {}

    // Add manually configured traits
    if (not empty(inputs.email)) traits.email := toString(inputs.email)
    if (not empty(inputs.user_name)) traits.name := toString(inputs.user_name)
    if (not empty(inputs.role)) traits.role := toString(inputs.role)
    if (not empty(inputs.accountStatus)) traits.accountStatus := toString(inputs.accountStatus)
    if (not empty(inputs.createdAt)) traits.createdAt := toString(inputs.createdAt)

    // Add all properties from the user traits mapping, but manual traits take precedence
    if (not empty(inputs.user_traits_mapping)) {
        for (let key, value in inputs.user_traits_mapping) {
            if (empty(traits[key]) and not empty(value)) {
                traits[key] := value
            }
        }
    }

    // Filter out traits with 'geoip', 'ip', or 'current_url' so we don't store them even if mapped
    let filteredTraits := {}
    for (let key, value in traits) {
        let lowerKey := lower(key)
        if (not (lowerKey like '%geoip%' or lowerKey like '%ip%' or lowerKey like '%current_url%')) {
            filteredTraits[key] := value
        }
    }

    body.traits := filteredTraits
} else if (type == 'group') {
    body.groupId := toString(inputs.groupId)

    let traits := {}

    // Add manually configured group traits
    if (not empty(inputs.group_name)) traits.name := toString(inputs.group_name)
    if (not empty(inputs.group_createdAt)) traits.createdAt := toString(inputs.group_createdAt)
    if (not empty(inputs.group_status)) traits.status := toString(inputs.group_status)
    if (not empty(inputs.group_plan)) traits.plan := toString(inputs.group_plan)
    if (not empty(inputs.group_mrr)) traits.mrr := toFloat(inputs.group_mrr)

    // Add all properties from the group traits mapping, but manual traits take precedence
    if (not empty(inputs.group_traits_mapping)) {
        for (let key, value in inputs.group_traits_mapping) {
            if (empty(traits[key]) and not empty(value)) {
                traits[key] := value
            }
        }
    }

    // Filter out traits with 'geoip', 'ip', or 'current_url' so we don't store them even if mapped
    let filteredTraits := {}
    for (let key, value in traits) {
        let lowerKey := lower(key)
        if (not (lowerKey like '%geoip%' or lowerKey like '%ip%' or lowerKey like '%current_url%')) {
            filteredTraits[key] := value
        }
    }

    body.traits := filteredTraits
}

// Determine URL and actual API key based on prefix
let url := 'https://in.accoil.com/segment'
let actualApiKey := inputs.apiKey
if (substring(lower(inputs.apiKey), 1, 4) == 'stg_') {
    url := 'https://instaging.accoil.com/segment'
    actualApiKey := substring(inputs.apiKey, 5)  // Strip the 'stg_' prefix
}

// Create Basic Auth header (actual API key as username, no password)
let credentials := base64Encode(f'{actualApiKey}:')

let res := fetch(url, {
    'method': 'POST',
    'headers': {
        'Authorization': f'Basic {credentials}',
        'Content-Type': 'application/json'
    },
    'body': body
})

if (res.status >= 400) {
    throw Error(f'Error from Accoil (status {res.status}): {res.body}')
}
`,
    inputs_schema: [
        // Common fields used across all event types
        {
            key: 'apiKey',
            type: 'string',
            label: 'API Key',
            description: 'Your Accoil.com API Key. You can find your API Key in your Accoil account settings.',
            secret: true,
            required: true,
        },
        {
            key: 'timestamp',
            type: 'string',
            label: 'Timestamp',
            description: 'Event timestamp in ISO8601 format',
            default: '{event.timestamp}',
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
                                key: "event not in ('$identify', '$set', '$pageview', '$screen', '$groupidentify')",
                                type: 'hogql',
                            },
                        ],
                    },
                ],
            },
            inputs_schema: [
                {
                    key: 'userId',
                    type: 'string',
                    label: 'User ID',
                    description: 'Unique identifier for the user',
                    default: '{event.distinct_id}',
                    required: true,
                },
                {
                    key: 'event',
                    type: 'string',
                    label: 'Event Name',
                    description: 'Name of the custom event being tracked',
                    default: '{event.event}',
                    required: false,
                },
            ],
        },
        {
            name: 'Page Calls',
            include_by_default: true,
            filters: {
                events: [
                    {
                        id: null,
                        name: 'All events',
                        type: 'events',
                        properties: [
                            {
                                key: "event in ('$pageview')",
                                type: 'hogql',
                            },
                        ],
                    },
                ],
            },
            inputs_schema: [
                {
                    key: 'userId',
                    type: 'string',
                    label: 'User ID',
                    description: 'Unique identifier for the user',
                    default: '{event.distinct_id}',
                    required: false,
                },
                {
                    key: 'name',
                    type: 'string',
                    label: 'Page Name',
                    description: 'Name of the page being viewed',
                    default: '{event.properties.title ?? event.properties.$pathname}',
                    required: false,
                },
            ],
        },
        {
            name: 'Screen Calls',
            include_by_default: true,
            filters: {
                events: [
                    {
                        id: null,
                        name: 'All events',
                        type: 'events',
                        properties: [
                            {
                                key: "event in ('$screen')",
                                type: 'hogql',
                            },
                        ],
                    },
                ],
            },
            inputs_schema: [
                {
                    key: 'userId',
                    type: 'string',
                    label: 'User ID',
                    description: 'Unique identifier for the user',
                    default: '{event.distinct_id}',
                    required: false,
                },
                {
                    key: 'name',
                    type: 'string',
                    label: 'Screen Name',
                    description: 'Name of the screen being viewed',
                    default: '{event.properties.$screen_name}',
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
                    key: 'userId',
                    type: 'string',
                    label: 'User ID',
                    description: 'Unique identifier for the user',
                    default: '{event.distinct_id}',
                    required: true,
                },
                {
                    key: 'email',
                    type: 'string',
                    label: 'Email',
                    description: 'User email address',
                    default: '{person.properties.email}',
                    required: false,
                },
                {
                    key: 'user_name',
                    type: 'string',
                    label: 'Name',
                    description: 'User full name',
                    default: '{person.properties.name}',
                    required: false,
                },
                {
                    key: 'role',
                    type: 'string',
                    label: 'Role',
                    description: 'User role or job title',
                    default: '{person.properties.role}',
                    required: false,
                },
                {
                    key: 'accountStatus',
                    type: 'string',
                    label: 'Account Status',
                    description: 'Account status (e.g., active, trial, churned)',
                    default: '{person.properties.account_status}',
                    required: false,
                },
                {
                    key: 'createdAt',
                    type: 'string',
                    label: 'Created At',
                    description: 'User creation date',
                    default: '{person.properties.created_at}',
                    required: false,
                },
                {
                    key: 'user_traits_mapping',
                    type: 'dictionary',
                    label: 'Additional User Traits',
                    description:
                        'Map person properties to user traits. Add key-value pairs where keys are trait names and values are person property references like {person.properties.company}. Note: traits with "geoip", "ip", or "current_url" in their key will not be sent.',
                    default: {},
                    required: false,
                },
            ],
        },
        {
            name: 'Group Calls',
            include_by_default: true,
            filters: {
                events: [
                    {
                        id: null,
                        name: 'All events',
                        type: 'events',
                        properties: [
                            {
                                key: "event in ('$groupidentify')",
                                type: 'hogql',
                            },
                        ],
                    },
                ],
            },
            inputs_schema: [
                {
                    key: 'userId',
                    type: 'string',
                    label: 'User ID',
                    description: 'Unique identifier for the user',
                    default: '{event.distinct_id}',
                    required: false,
                },
                {
                    key: 'anonymousId',
                    type: 'string',
                    label: 'Anonymous ID',
                    description: 'Anonymous identifier for the user',
                    default: '{event.properties.$anon_distinct_id}',
                    required: false,
                },
                {
                    key: 'groupId',
                    type: 'string',
                    label: 'Group ID',
                    description: 'Group identifier',
                    default: '{event.properties.$group_key}',
                    required: false,
                },
                {
                    key: 'group_name',
                    type: 'string',
                    label: 'Group Name',
                    description: 'Name of the group/organization',
                    default: '{event.properties.$group_set.name}',
                    required: false,
                },
                {
                    key: 'group_plan',
                    type: 'string',
                    label: 'Plan',
                    description: 'Group subscription plan',
                    default: '{event.properties.$group_set.plan}',
                    required: false,
                },
                {
                    key: 'group_mrr',
                    type: 'string',
                    label: 'MRR',
                    description: 'Monthly recurring revenue',
                    default: '{event.properties.$group_set.mrr}',
                    required: false,
                },
                {
                    key: 'group_status',
                    type: 'string',
                    label: 'Status',
                    description: 'Group status (e.g., active, trial)',
                    default: '{event.properties.$group_set.status}',
                    required: false,
                },
                {
                    key: 'group_createdAt',
                    type: 'string',
                    label: 'Created At',
                    description: 'Group creation date',
                    default: '{event.properties.$group_set.created_at}',
                    required: false,
                },
                {
                    key: 'group_traits_mapping',
                    type: 'dictionary',
                    label: 'Additional Group Traits',
                    description:
                        'Map group properties to group traits. Add key-value pairs where keys are trait names and values are group property references like {event.properties.$group_set.industry}. Note: traits with "geoip", "ip", or "current_url" in their key will not be sent.',
                    default: {},
                    required: false,
                },
            ],
        },
    ],
}
