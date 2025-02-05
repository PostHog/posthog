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
                label: 'Avo API Key',
                type: 'string',
                default: '',
                required: true,
                secret: false,
            },
            {
                key: 'environment',
                label: 'Environment',
                type: 'string',
                default: 'dev',
                required: false,
                secret: false,
            },
            {
                key: 'appName',
                label: 'App name',
                type: 'string',
                default: 'PostHog',
                required: false,
                secret: false,
            },
            {
                key: 'excludeEvents',
                label: 'Events to exclude',
                type: 'string',
                description: 'Comma-separated list of events that will not be sent to Avo.',
                default: '',
                required: false,
                secret: false,
            },
            {
                key: 'includeEvents',
                label: 'Events to include',
                type: 'string',
                description: 'Comma separated list of events to send to Avo (will send all if left empty).',
                default: '',
                required: false,
                secret: false,
            },
            {
                key: 'excludeProperties',
                label: 'Properties to exclude',
                type: 'string',
                description: 'Comma-separated list of event properties that will not be sent to Avo.',
                default: '',
                required: false,
                secret: false,
            },
            {
                key: 'includeProperties',
                label: 'Properties to include',
                type: 'string',
                description: 'Comma separated list of event properties to send to Avo (will send all if left empty).',
                default: '',
                required: false,
                secret: false,
            },
        ],
    },
}
