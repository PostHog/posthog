import { HogFunctionInputSchemaType } from '~/cdp/types'
import { HogFunctionTemplate } from '~/cdp/types'

// Based on https://developers.google.com/analytics/devguide/collection/protocol/ga4/reference

const build_inputs = (): HogFunctionInputSchemaType[] => {
    return [
        {
            key: 'clientId',
            type: 'string',
            label: 'Client ID',
            description:
                'A unique identifier for the client. Use the GA client_id if available, otherwise falls back to distinct_id.',
            default: '{person.properties.$ga_client_id ?? event.distinct_id}',
            secret: false,
            required: true,
        },
        {
            key: 'eventName',
            type: 'string',
            label: 'Event name',
            description:
                'The name of the event to send to GA4. Can be a standard GA4 event name (e.g. purchase, sign_up) or a custom event name.',
            default: '{event.event}',
            secret: false,
            required: true,
        },
        {
            key: 'eventParameters',
            type: 'dictionary',
            label: 'Event parameters',
            description: 'Additional parameters to include with the event.',
            default: {},
            secret: false,
            required: false,
        },
        {
            key: 'userId',
            type: 'string',
            label: 'User ID',
            description: 'A unique identifier for the user. Maps to the user_id field in GA4.',
            default: '',
            secret: false,
            required: false,
        },
    ]
}

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'destination',
    id: 'template-google-analytics-4',
    name: 'Google Analytics 4',
    description: 'Send events to Google Analytics 4 via the Measurement Protocol',
    icon_url: '/static/coming-soon-destinations/Google_Analytics_4.svg',
    category: ['Analytics'],
    code_language: 'hog',
    code: `
if (empty(inputs.clientId)) {
    print('Empty \`clientId\`. Skipping...')
    return
}

let event := {
    'name': inputs.eventName,
    'params': inputs.eventParameters ?? {}
}

let body := {
    'client_id': inputs.clientId,
    'events': [event]
}

if (not empty(inputs.userId)) {
    body.user_id := inputs.userId
}

let res := fetch(f'https://www.google-analytics.com/mp/collect?measurement_id={inputs.measurementId}&api_secret={inputs.apiSecret}', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json'
    },
    'body': body
})

if (res.status >= 400) {
    throw Error(f'Error from Google Analytics 4 (status {res.status}): {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'measurementId',
            type: 'string',
            label: 'Measurement ID',
            description: 'Your GA4 Measurement ID (e.g. G-XXXXXXXXXX). Found in Admin > Data Streams.',
            secret: false,
            required: true,
        },
        {
            key: 'apiSecret',
            type: 'string',
            label: 'API Secret',
            description:
                'Measurement Protocol API Secret. Create one in Admin > Data Streams > Measurement Protocol API secrets.',
            secret: true,
            required: true,
        },
    ],
    mapping_templates: [
        {
            name: 'Page view',
            include_by_default: true,
            filters: {
                events: [{ id: '$pageview', type: 'events' }],
            },
            inputs_schema: [
                ...build_inputs().map((input) => {
                    if (input.key === 'eventName') {
                        return { ...input, default: 'page_view' }
                    }
                    if (input.key === 'eventParameters') {
                        return {
                            ...input,
                            default: {
                                page_location: '{event.properties.$current_url}',
                                page_referrer: '{event.properties.$referrer}',
                                page_title: '{event.properties.title}',
                            },
                        }
                    }
                    return input
                }),
            ],
        },
        {
            name: 'Custom event',
            include_by_default: false,
            filters: {
                events: [],
            },
            inputs_schema: [...build_inputs()],
        },
    ],
}
