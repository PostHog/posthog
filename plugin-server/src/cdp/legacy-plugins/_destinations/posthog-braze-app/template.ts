import { LegacyDestinationPlugin } from '../../types'
import { onEvent } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const brazePlugin: LegacyDestinationPlugin = {
    onEvent,
    template: {
        free: false,
        status: 'deprecated',
        type: 'destination',
        id: 'plugin-posthog-braze-plugin',
        name: 'Braze',
        description: 'Import analytics from Braze and export PostHog events to Braze.',
        icon_url: 'https://raw.githubusercontent.com/PostHog/posthog-braze-plugin/main/logo.png',
        category: [],
        hog: 'return event',
        inputs_schema: [
            {
                key: 'brazeEndpoint',
                description:
                    'The endpoint identifier where your Braze instance is located, [see the docs here](https://www.braze.com/docs/api/basics)',
                type: 'choice',
                default: '',
                required: true,
                secret: true,
                choices: [
                    { value: 'US-01', label: 'US-01' },
                    { value: 'US-02', label: 'US-02' },
                    { value: 'US-03', label: 'US-03' },
                    { value: 'US-04', label: 'US-04' },
                    { value: 'US-05', label: 'US-05' },
                    { value: 'US-06', label: 'US-06' },
                    { value: 'US-08', label: 'US-08' },
                    { value: 'EU-01', label: 'EU-01' },
                    { value: 'EU-02', label: 'EU-02' },
                ],
            },
            {
                key: 'apiKey',
                description: 'Your Braze API Key, [see the docs here](https://www.braze.com/docs/api/api_key/)',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'eventsToExport',
                description:
                    'A comma separated list of events you want to export to Braze. Leave empty to export no events.',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'userPropertiesToExport',
                description:
                    'A comma separated list of user properties you want to export to Braze. Leave empty to export no user properties.',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'eventsToExportUserPropertiesFrom',
                description:
                    'A comma separated list of events you want to find user properties in to export to Braze. Leave empty to export no user properties.',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
        ],
    },
}
