import { NativeTemplate } from '~/cdp/types'

export const template: NativeTemplate = {
    free: false,
    status: 'hidden',
    type: 'destination',
    id: 'native-email',
    name: 'Native email',
    description: 'Sends a native email templated by the incoming event data',
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
        {
            type: 'email',
            key: 'email',
            label: 'Email message',
            integration: 'email',
            required: true,
            default: '',
            secret: false,
            description: 'The email message to send.',
        },
    ],
}
