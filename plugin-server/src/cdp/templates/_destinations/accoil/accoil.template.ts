import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'beta',
    free: true,
    type: 'destination',
    id: 'template-accoil',
    name: 'Accoil',
    description: 'Send events to Accoil',
    icon_url: '/static/services/accoil.com.png',
    category: ['Analytics'],
    code_language: 'hog',
    code: `
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
    'timestamp': toString(inputs.timestamp),
    'userId': toString(inputs.userId)
}

// Add anonymousId if provided and not empty
if (not empty(inputs.anonymousId)) {
    body.anonymousId := toString(inputs.anonymousId)
}

// Type-specific fields
if (type == 'track') {
    body.event := toString(inputs.event)
} else if (type == 'page' or type == 'screen') {
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

    body.traits := traits
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

    body.traits := traits
}

// Determine URL based on API key prefix
let url := 'https://in.accoil.com/segment'
if (substring(lower(inputs.apiKey), 1, 4) == 'stg_') {
    url := 'https://instaging.accoil.com/segment'
}

// Create Basic Auth header (API key as username, no password)
let credentials := base64Encode(f'{inputs.apiKey}:')

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
        {
            key: 'apiKey',
            type: 'string',
            label: 'Accoil API Key',
            description: 'Your Accoil API key for authentication',
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
        {
            key: 'userId',
            type: 'string',
            label: 'User ID',
            description: 'Unique identifier for the user',
            default: '{event.distinct_id}',
            required: true,
        },
        {
            key: 'anonymousId',
            type: 'string',
            label: 'Anonymous ID',
            description: 'Anonymous identifier for the user (optional)',
            default: '{event.properties.$anon_distinct_id}',
            required: false,
        },
        {
            key: 'event',
            type: 'string',
            label: 'Track: Event Name',
            description: 'Name of the event (only used for track calls)',
            default: '{event.event}',
            required: false,
        },
        {
            key: 'name',
            type: 'string',
            label: 'Page/Screen: Name',
            description: 'Name of the page or screen (only used for page/screen calls)',
            default: '{event.properties.title ?? event.properties.$pathname ?? event.properties.$screen_name}',
            required: false,
        },
        {
            key: 'email',
            type: 'string',
            label: 'Identify: Email',
            description: 'User email (only used for identify calls)',
            default: '{person.properties.email}',
            required: false,
        },
        {
            key: 'user_name',
            type: 'string',
            label: 'Identify: User Name',
            description: 'User name (only used for identify calls)',
            default: '{person.properties.name}',
            required: false,
        },
        {
            key: 'role',
            type: 'string',
            label: 'Identify: Role',
            description: 'User role (only used for identify calls)',
            default: '{person.properties.role}',
            required: false,
        },
        {
            key: 'accountStatus',
            type: 'string',
            label: 'Identify: Account Status',
            description: 'Account status (only used for identify calls)',
            default: '{person.properties.account_status}',
            required: false,
        },
        {
            key: 'createdAt',
            type: 'string',
            label: 'Identify: Created At',
            description: 'User creation date (only used for identify calls)',
            default: '{person.properties.created_at}',
            required: false,
        },
        {
            key: 'user_traits_mapping',
            type: 'dictionary',
            label: 'Identify: Additional User Traits',
            description: 'Object containing additional user traits to include (only used for identify calls)',
            default: '{person.properties}',
            required: false,
        },
        {
            key: 'groupId',
            type: 'string',
            label: 'Group: Group ID',
            description: 'Group identifier (only used for group calls)',
            default: '{event.properties.$group_key}',
            required: false,
        },
        {
            key: 'group_name',
            type: 'string',
            label: 'Group: Name',
            description: 'Group name (only used for group calls)',
            default: '{event.properties.$group_set.name}',
            required: false,
        },
        {
            key: 'group_createdAt',
            type: 'string',
            label: 'Group: Created At',
            description: 'Group creation date (only used for group calls)',
            default: '{event.properties.$group_set.created_at}',
            required: false,
        },
        {
            key: 'group_status',
            type: 'string',
            label: 'Group: Status',
            description: 'Group status (only used for group calls)',
            default: '{event.properties.$group_set.status}',
            required: false,
        },
        {
            key: 'group_plan',
            type: 'string',
            label: 'Group: Plan',
            description: 'Group plan (only used for group calls)',
            default: '{event.properties.$group_set.plan}',
            required: false,
        },
        {
            key: 'group_mrr',
            type: 'number',
            label: 'Group: MRR',
            description: 'Group monthly recurring revenue (only used for group calls)',
            default: '{event.properties.$group_set.mrr}',
            required: false,
        },
        {
            key: 'group_traits_mapping',
            type: 'dictionary',
            label: 'Group: Additional Group Traits',
            description: 'Object containing additional group traits to include (only used for group calls)',
            default: '{event.properties.$group_set}',
            required: false,
        },
    ],
    filters: {
        events: [],
        actions: [],
        filter_test_accounts: true,
    },
}
