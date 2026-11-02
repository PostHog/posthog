import { NativeTemplate } from '~/cdp/types'

import { webhookRequestInputs } from '../webhook/webhook-inputs'

export const template: NativeTemplate = {
    free: false,
    status: 'hidden',
    type: 'destination',
    id: 'native-webhook',
    name: 'Native HTTP Webhook',
    description: 'Sends a native webhook templated by the incoming event data',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    perform: (request, { payload }) => {
        try {
            return request(payload.url, {
                method: payload.method,
                headers: payload.headers,
                json: payload.body,
            })
        } catch (error) {
            throw new Error(error.message)
        }
    },
    inputs_schema: [
        ...webhookRequestInputs,
        {
            key: 'headers',
            type: 'dictionary',
            label: 'Headers',
            secret: false,
            required: false,
            default: { 'Content-Type': 'application/json' },
            description: 'HTTP headers to send in the request.',
        },
        {
            key: 'debug',
            type: 'boolean',
            label: 'Log responses',
            description: 'Logs the response of http calls for debugging.',
            secret: false,
            required: false,
            default: false,
        },
    ],
}
