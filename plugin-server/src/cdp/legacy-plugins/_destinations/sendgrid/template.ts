import { LegacyDestinationPlugin } from '../../types'
import { onEvent, setupPlugin } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const sendgridPlugin: LegacyDestinationPlugin = {
    setupPlugin: setupPlugin as any,
    onEvent,
    template: {
        free: false,
        status: 'deprecated',
        type: 'destination',
        id: 'plugin-sendgrid-plugin',
        name: 'Sendgrid',
        description: 'Send emails and user data to Sendgrid when you identify users using PostHog.',
        icon_url: 'https://raw.githubusercontent.com/PostHog/sendgrid-plugin/main/logo.png',
        category: [],
        code_language: 'javascript',
        code: 'return event',
        inputs_schema: [
            {
                templating: false,
                key: 'sendgridApiKey',
                label: 'Sendgrid API Key',
                type: 'string',
                description: 'The key needs PUT access',
                required: true,
                secret: true,
            },
            {
                templating: false,
                key: 'customFields',
                label: 'Custom fields',
                type: 'string',
                description:
                    'Comma separated list of additional properties that will be sent to Sendgrid as custom fields. Optionally, you can define an alternative key for the field in Sendgrid. E.g. myProp1=my_prop1,myProp2=my_prop2',
                default: '',
                required: false,
                secret: false,
            },
        ],
    },
}
