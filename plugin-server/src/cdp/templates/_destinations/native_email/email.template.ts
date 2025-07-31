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
        console.log('TODO: implement native email with payload:', payload)
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
