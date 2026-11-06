import { LegacyDestinationPlugin } from '../../types'
import { onEvent } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const brazePlugin: LegacyDestinationPlugin = {
    onEvent,
    template: {
        free: false,
        status: 'deprecated',
        type: 'destination',
        id: 'plugin-posthog-braze-app',
        name: 'Braze',
        description: 'Import analytics from Braze and export PostHog events to Braze.',
        icon_url: 'https://raw.githubusercontent.com/PostHog/posthog-braze-plugin/main/logo.png',
        category: [],
        code_language: 'javascript',
        code: 'return event',
        inputs_schema: [
            {
                templating: false,
                key: 'brazeEndpoint',
                label: 'Braze REST Endpoint',
                type: 'choice',
                description:
                    'The endpoint identifier where your Braze instance is located, [see the docs here](https://www.braze.com/docs/api/basics)',
                required: true,
                secret: false,
                choices: [
                    {
                        value: 'US-01',
                        label: 'US-01',
                    },
                    {
                        value: 'US-02',
                        label: 'US-02',
                    },
                    {
                        value: 'US-03',
                        label: 'US-03',
                    },
                    {
                        value: 'US-04',
                        label: 'US-04',
                    },
                    {
                        value: 'US-05',
                        label: 'US-05',
                    },
                    {
                        value: 'US-06',
                        label: 'US-06',
                    },
                    {
                        value: 'US-08',
                        label: 'US-08',
                    },
                    {
                        value: 'EU-01',
                        label: 'EU-01',
                    },
                    {
                        value: 'EU-02',
                        label: 'EU-02',
                    },
                ],
            },
            {
                templating: false,
                key: 'apiKey',
                label: 'API Key',
                type: 'string',
                description: 'Your Braze API Key, [see the docs here](https://www.braze.com/docs/api/api_key/)',
                required: true,
                secret: true,
            },
            {
                templating: false,
                key: 'eventsToExport',
                label: 'Events to Export',
                type: 'string',
                description:
                    'A comma separated list of events you want to export to Braze. Leave empty to export no events.',
                default: '',
                required: false,
                secret: false,
            },
            {
                templating: false,
                key: 'userPropertiesToExport',
                label: 'User Properties to Export',
                type: 'string',
                description:
                    'A comma separated list of user properties you want to export to Braze. Leave empty to export no user properties.',
                default: '',
                required: false,
                secret: false,
            },
            {
                templating: false,
                key: 'eventsToExportUserPropertiesFrom',
                label: 'Events for user properties search',
                type: 'string',
                description:
                    'A comma separated list of events you want to find user properties in to export to Braze. Leave empty to export no user properties.',
                default: '',
                required: false,
                secret: false,
            },
        ],
    },
}
