import { EXTEND_OBJECT_KEY } from '~/cdp/services/hog-executor.service'
import { NativeTemplate } from '~/cdp/templates/types'

export const template: NativeTemplate = {
    free: false,
    status: 'hidden',
    type: 'destination',
    id: 'native-posthog',
    name: 'PostHog',
    description: 'Sends events to PostHog',
    icon_url: '/static/posthog-icon.svg',
    category: ['Analytics'],
    inputs_schema: [
        {
            key: 'apiKey',
            type: 'string',
            label: 'API Key',
            secret: false,
            required: true,
            description: 'API Key to authenticate the request.',
        },
    ],
    mapping_templates: [
        {
            name: 'Send an event',
            include_by_default: true,
            filters: {
                events: [
                    {
                        id: null,
                        name: 'All events',
                        order: 0,
                        type: 'events',
                    },
                ],
            },
            associated_action: 'event',
            inputs_schema: [
                {
                    key: 'eventName',
                    type: 'string',
                    label: 'Event Name',
                    secret: false,
                    required: true,
                    description: 'The name of the event to send.',
                },
                {
                    key: 'eventId',
                    type: 'string',
                    label: 'Event ID',
                    secret: false,
                    required: false,
                    description: 'The ID of the event to send.',
                },
                {
                    key: 'eventProperties',
                    type: 'dictionary',
                    label: 'Event Properties',
                    secret: false,
                    default: {
                        [EXTEND_OBJECT_KEY]: '{event.properties}',
                    },
                    required: false,
                    description: 'Properties to send with the event.',
                },
            ],
        },
    ],
    actions: {
        event: {
            perform: (request, { payload }) => {
                try {
                    return request('http://localhost:2080/7c138c0e-e208-4bc0-8378-4bbbdedad5bf', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            Authorization: `Bearer ${payload.apiKey}`,
                        },
                        json: {
                            event: payload.eventName,
                            properties: payload.eventProperties,
                        },
                    })
                } catch (error) {
                    throw new Error(error.message)
                }
            },
        },
    },
}
