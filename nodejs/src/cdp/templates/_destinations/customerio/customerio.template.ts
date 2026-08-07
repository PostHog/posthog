import { HogFunctionTemplate } from '~/cdp/types'

// Based off of https://customer.io/docs/api/track/#operation/entity

export const template: HogFunctionTemplate = {
    status: 'stable',
    free: false,
    type: 'destination',
    id: 'template-customerio',
    name: 'Customer.io',
    description: 'Identify or track events against customers in Customer.io',
    icon_url: '/static/services/customerio.png',
    category: ['Email Marketing'],
    code_language: 'hog',
    // Trimmed so the stored code matches what existing functions copied into their `hog`,
    // which is what the UI diffs to decide whether a function is modified. The ` `
    // below is a non-breaking space kept for the same reason — normalizing it would mark
    // every live Customer.io function as modified.
    code: `
let action := inputs.action
let name := event.event


if (empty(inputs.identifier_value) or empty(inputs.identifier_key)) {
    print('No identifier set. Skipping as identifier is required.')
    return
}

let identifiers := {
    inputs.identifier_key: inputs.identifier_value
}

if (action == 'automatic') {
    if (event.event in ('$identify', '$set')) {
        action := 'identify'
        name := null
    } else if (event.event == '$pageview') {
        action := 'page'
        name := event.properties.$current_url
    } else if (event.event == '$screen') {
        action := 'screen'
        name := event.properties.$screen_name
    } else {
        action := 'event'
    }
}

let attributes := inputs.include_all_properties ? action == 'identify' ? person.properties : event.properties : {}
if (inputs.include_all_properties and action != 'identify' and not empty(event.elements_chain)) {
    attributes['$elements_chain'] := event.elements_chain
}
let timestamp := toInt(toUnixTimestamp(toDateTime(event.timestamp)))

for (let key, value in inputs.attributes) {
    attributes[key] := value
}

for (let key, value in attributes) {
    if (value and typeof(value) == 'string') {
        if (length(value) > 1000) {
            attributes[key] := substring(value, 1, 1000)
        }
    }
}

let res := fetch(f'https://{inputs.host}/api/v2/entity', {
    'method': 'POST',
    'headers': {
        'User-Agent': 'PostHog Customer.io App',
        'Authorization': f'Basic {base64Encode(f'{inputs.site_id}:{inputs.token}')}',
        'Content-Type': 'application/json'
    },
    'body': {
        'type': 'person',
        'action': action,
        'name': name,
        'identifiers': identifiers,
        'attributes': attributes,
        'timestamp': timestamp
    }
})

if (res.status >= 400) {
    throw Error(f'Error from customer.io api: {res.status}: {res.body}');
}
`.trim(),
    inputs_schema: [
        {
            key: 'site_id',
            type: 'string',
            label: 'Customer.io site ID',
            secret: false,
            required: true,
        },
        {
            key: 'token',
            type: 'string',
            label: 'Customer.io API Key',
            description:
                'You can find your API key in your Customer.io account settings (https://fly.customer.io/settings/api_credentials)',
            secret: true,
            required: true,
        },
        {
            key: 'host',
            type: 'choice',
            choices: [
                {
                    label: 'US (track.customer.io)',
                    value: 'track.customer.io',
                },
                {
                    label: 'EU (track-eu.customer.io)',
                    value: 'track-eu.customer.io',
                },
            ],
            label: 'Customer.io region',
            description: 'Use the EU variant if your Customer.io account is based in the EU region',
            default: 'track.customer.io',
            secret: false,
            required: true,
        },
        {
            key: 'identifier_key',
            type: 'choice',
            label: 'Identifier key',
            description:
                'The kind of identifier to be used. See here for more information: https://customer.io/docs/api/track/#operation/entity',
            default: 'email',
            choices: [
                {
                    label: 'Email',
                    value: 'email',
                },
                {
                    label: 'ID',
                    value: 'id',
                },
                {
                    label: 'Customer.io ID',
                    value: 'cio_id',
                },
            ],
            secret: false,
            required: true,
        },
        {
            key: 'identifier_value',
            type: 'string',
            label: 'Identifier value',
            description:
                'The value to be used for the identifier. If the value is empty nothing will be sent. See here for more information: https://customer.io/docs/api/track/#operation/entity',
            default: '{person.properties.email}',
            secret: false,
            required: true,
        },
        {
            key: 'action',
            type: 'choice',
            label: 'Action',
            description:
                'Choose the action to be tracked. Automatic will convert $identify, $pageview and $screen to identify, page and screen automatically - otherwise defaulting to event',
            default: 'automatic',
            choices: [
                {
                    label: 'Automatic',
                    value: 'automatic',
                },
                {
                    label: 'Identify',
                    value: 'identify',
                },
                {
                    label: 'Event',
                    value: 'event',
                },
                {
                    label: 'Page',
                    value: 'page',
                },
                {
                    label: 'Screen',
                    value: 'screen',
                },
                {
                    label: 'Delete',
                    value: 'delete',
                },
            ],
            secret: false,
            required: true,
        },
        {
            key: 'include_all_properties',
            type: 'boolean',
            label: 'Include all properties as attributes',
            description:
                'If set, all event properties will be included as attributes. Individual attributes can be overridden below. For identify events the Person properties will be used.',
            default: false,
            secret: false,
            required: true,
        },
        {
            key: 'attributes',
            type: 'dictionary',
            label: 'Attribute mapping',
            description:
                'Map of Customer.io attributes and their values. You can use the filters section to filter out unwanted events.',
            default: {
                email: '{person.properties.email}',
                lastname: '{person.properties.lastname}',
                firstname: '{person.properties.firstname}',
            },
            secret: false,
            required: false,
        },
    ],
    filters: {
        events: [
            { id: '$identify', name: '$identify', type: 'events', order: 0 },
            { id: '$pageview', name: '$pageview', type: 'events', order: 0 },
        ],
        actions: [],
        filter_test_accounts: true,
    },
}
