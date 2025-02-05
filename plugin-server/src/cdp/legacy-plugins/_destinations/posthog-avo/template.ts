import { LegacyDestinationPlugin } from '../../types'
import { onEvent, setupPlugin } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const avoPlugin: LegacyDestinationPlugin = {
    setupPlugin: setupPlugin as any,
    onEvent,
    template: {
        free: false,
        status: 'deprecated',
        type: 'destination',
        id: 'plugin-posthog-avo-plugin',
        name: 'Avo Inspector Plugin',
        description: 'Export PostHog events to Avo inspector.',
        icon_url: 'https://raw.githubusercontent.com/PostHog/posthog-avo-plugin/main/logo.png',
        category: [],
        hog: 'return event',
        inputs_schema: [
            {
                key: 'avoApiKey',
                description: '',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'environment',
                description: '',
                type: 'string',
                default: 'dev',
                required: true,
                secret: true,
            },
            {
                key: 'appName',
                description: '',
                type: 'string',
                default: 'PostHog',
                required: true,
                secret: true,
            },
            {
                key: 'excludeEvents',
                description: 'Comma-separated list of events that will not be sent to Avo.',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'includeEvents',
                description: 'Comma separated list of events to send to Avo (will send all if left empty).',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'excludeProperties',
                description: 'Comma-separated list of event properties that will not be sent to Avo.',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'includeProperties',
                description: 'Comma separated list of event properties to send to Avo (will send all if left empty).',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
        ],
    },
}
