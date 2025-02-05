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
        id: 'plugin-salesforce-plugin',
        name: 'Salesforce Export Plugin',
        description: 'Relay PostHog events to Salesforce',
        icon_url: 'https://raw.githubusercontent.com/PostHog/salesforce-plugin/main/logo.png',
        category: [],
        hog: 'return event',
        inputs_schema: [
            {
                key: 'salesforceHost',
                label: 'Salesforce Service Host',
                type: 'string',
                description: 'Usually in the format of https://<org name>.my.salesforce.com',
                required: true,
                secret: false,
            },
            {
                key: 'username',
                label: 'Username',
                type: 'string',
                required: true,
                secret: false,
            },
            {
                key: 'password',
                label: 'Password',
                type: 'string',
                required: false,
                secret: true,
            },
            {
                key: 'consumerKey',
                label: 'Consumer key',
                type: 'string',
                required: true,
                secret: true,
            },
            {
                key: 'consumerSecret',
                label: 'Consumer secret',
                type: 'string',
                required: true,
                secret: true,
            },
            {
                key: 'eventsToInclude',
                label: 'Events to include',
                type: 'string',
                description: 'Comma separated list of events to include. If not set, no events will be sent',
                default: '',
                required: false,
                secret: false,
            },
            {
                key: 'eventPath',
                label: 'Path of the url where events will go to. No leading forward slash',
                type: 'string',
                default: '',
                required: false,
                secret: false,
            },
            {
                key: 'eventMethodType',
                label: 'The type of method for the event url',
                type: 'string',
                default: 'POST',
                required: false,
                secret: false,
            },
            {
                key: 'propertiesToInclude',
                label: 'Properties to include',
                type: 'string',
                description:
                    'Comma separated list of properties to include. If not set, all properties of the event will be sent',
                default: '',
                required: false,
                secret: false,
            },
            {
                key: 'eventEndpointMapping',
                label: 'Event endpoint mapping',
                type: 'json',
                description:
                    '⚠️ For advanced uses only ⚠️ Allows you to map events to different SalesForce endpoints. See https://github.com/PostHog/salesforce-plugin/blob/main/README.md for an example.',
                default: '',
                required: false,
                secret: false,
            },
            {
                key: 'fieldMappings',
                label: 'Event to salesforce field mapping',
                type: 'json',
                description:
                    "SalesForce can be strict about field names, if your posthog event property names don't match then you can map them using this. See https://github.com/PostHog/salesforce-plugin/blob/main/README.md for an example.",
                default: '',
                required: false,
                secret: false,
            },
            {
                key: 'debugLogging',
                label: 'Enable debug logging',
                type: 'choice',
                description: 'turn on debug logging to get _much_ more logging',
                default: 'debug logging off',
                required: false,
                secret: false,
                choices: [
                    {
                        value: 'debug logging on',
                        label: 'debug logging on',
                    },
                    {
                        value: 'debug logging off',
                        label: 'debug logging off',
                    },
                ],
            },
        ],
    },
}
