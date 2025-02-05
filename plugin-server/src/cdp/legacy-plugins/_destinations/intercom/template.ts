import { LegacyDestinationPlugin } from '../../types'
import { onEvent } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const intercomPlugin: LegacyDestinationPlugin = {
    onEvent,
    template: {
        free: false,
        status: 'deprecated',
        type: 'destination',
        id: 'plugin-posthog-intercom-plugin',
        name: 'Intercom',
        description: 'This plugin will send events to Intercom.',
        icon_url: 'https://raw.githubusercontent.com/posthog/posthog-intercom-plugin/main/logo.png',
        category: [],
        hog: `return event`,
        inputs_schema: [
            {
                key: 'intercomApiKey',
                description:
                    'Create an [Intercom app](https://developers.intercom.com/building-apps/), then go to Configure > Authentication to find your key.',
                label: 'Intercom API Key',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'triggeringEvents',
                description:
                    "A comma-separated list of PostHog events you want to send to Intercom (e.g.: '$identify,mycustomevent' ).",
                label: 'Triggering events',
                type: 'string',
                default: '$identify',
                required: true,
            },
            {
                key: 'ignoredEmailDomains',
                description:
                    "A comma-separated list of email domains to ignore and not send events for in Intercom (e.g. 'posthog.com,dev.posthog.com' ).",
                label: 'Email domains to skip',
                type: 'string',
                default: '',
                required: false,
            },
            {
                key: 'useEuropeanDataStorage',
                description: "Send events to api.eu.intercom.com, if you are using Intercom's European Data Hosting.",
                label: 'Send events to European Data Hosting',
                type: 'choice',
                default: 'No',
                choices: [
                    { value: 'Yes', label: 'Yes' },
                    { value: 'No', label: 'No' },
                ],
                required: false,
            },
        ],
    },
}
