import { LegacyDestinationPlugin } from '../../types'
import { onEvent, setupPlugin } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const salesforcePlugin: LegacyDestinationPlugin = {
    setupPlugin: setupPlugin as any,
    onEvent,
    template: {
        free: false,
        status: 'deprecated',
        type: 'destination',
        id: 'plugin-',
        name: 'Salesforce Export Plugin',
        description: 'Relay PostHog events to Salesforce',
        icon_url: 'https://raw.githubusercontent.com/PostHog/salesforce-plugin/main/logo.png',
        category: [],
        hog: 'return event',
        inputs_schema: [
            {
                key: 'salesforceHost',
                description: 'Usually in the format of https://<org name>.my.salesforce.com',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'username',
                description: '',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'password',
                description: '',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'consumerKey',
                description: '',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'consumerSecret',
                description: '',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'eventsToInclude',
                description: 'Comma separated list of events to include. If not set, no events will be sent',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'eventPath',
                description: '',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'eventMethodType',
                description: '',
                type: 'string',
                default: 'POST',
                required: true,
                secret: true,
            },
            {
                key: 'propertiesToInclude',
                description:
                    'Comma separated list of properties to include. If not set, all properties of the event will be sent',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'eventEndpointMapping',
                description:
                    '⚠️ For advanced uses only ⚠️ Allows you to map events to different SalesForce endpoints. See https://github.com/PostHog/salesforce-plugin/blob/main/README.md for an example.',
                type: 'json',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'fieldMappings',
                description:
                    "SalesForce can be strict about field names, if your posthog event property names don't match then you can map them using this. See https://github.com/PostHog/salesforce-plugin/blob/main/README.md for an example.",
                type: 'json',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'debugLogging',
                description: 'turn on debug logging to get _much_ more logging',
                type: 'choice',
                default: 'debug logging off',
                required: true,
                secret: true,
                choices: [
                    { value: 'debug logging off', label: 'debug logging off' },
                    { value: 'debug logging on', label: 'debug logging on' },
                ],
            },
        ],
    },
}
