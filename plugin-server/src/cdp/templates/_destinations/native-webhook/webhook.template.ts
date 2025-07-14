import { NativeTemplate } from '~/cdp/templates/types'

export const template: NativeTemplate = {
    free: false,
    status: 'hidden',
    type: 'destination',
    id: 'native-webhook',
    name: 'Native HTTP Webhook',
    description: 'Sends events to a native HTTP webhook',
    icon_url: '/static/webhook-icon.svg',
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
            name: 'Send a request',
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
            associated_action: 'send',
            inputs_schema: [
                {
                    key: 'url',
                    type: 'string',
                    label: 'URL',
                    secret: false,
                    required: true,
                    description: 'The URL to send the request to.',
                    format: 'uri',
                },
                {
                    key: 'method',
                    type: 'string',
                    label: 'Method',
                    secret: false,
                    required: true,
                    default: 'POST',
                    choices: [
                        {
                            label: 'POST',
                            value: 'POST',
                        },
                        {
                            label: 'GET',
                            value: 'GET',
                        },
                        {
                            label: 'PUT',
                            value: 'PUT',
                        },
                        {
                            label: 'DELETE',
                            value: 'DELETE',
                        },
                        {
                            label: 'PATCH',
                            value: 'PATCH',
                        },
                    ],
                    description: 'The HTTP method to use.',
                },
                {
                    key: 'body',
                    type: 'dictionary',
                    label: 'Body',
                    secret: false,
                    default: {
                        event: '{event.event}',
                        person: '{person.id}',
                    },
                    required: false,
                    description: 'The body of the request.',
                },
            ],
        },
    ],
    actions: {
        send: {
            perform: (request, { payload }) => {
                try {
                    return request(payload.url, {
                        method: payload.method,
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        json: payload.body,
                    })
                } catch (error) {
                    throw new Error(error.message)
                }
            },
        },
    },
}
