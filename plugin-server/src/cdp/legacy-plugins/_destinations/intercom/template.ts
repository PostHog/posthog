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
        description: 'Send event data to Intercom on PostHog events.',
        icon_url: 'https://raw.githubusercontent.com/PostHog/posthog-intercom-plugin/main/logo.png',
        category: [],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [
            {
                templating: false,
                key: 'intercomApiKey',
                label: 'Intercom API Key',
                type: 'string',
                description:
                    'Create an [Intercom app](https://developers.intercom.com/building-apps/), then go to Configure > Authentication to find your key.',
                required: true,
                secret: true,
            },
            {
                templating: false,
                key: 'triggeringEvents',
                label: 'Triggering events',
                type: 'string',
                description:
                    'A comma-separated list of PostHog events you want to send to Intercom (e.g.: `$identify,mycustomevent` ).',
                default: '$identify',
                required: true,
                secret: false,
            },
            {
                templating: false,
                key: 'ignoredEmailDomains',
                label: 'Email domains to skip',
                type: 'string',
                description:
                    'A comma-separated list of email domains to ignore and not send events for in Intercom (e.g. `posthog.com,dev.posthog.com` ).',
                default: '',
                required: false,
                secret: false,
            },
            {
                templating: false,
                key: 'useEuropeanDataStorage',
                label: 'Send events to European Data Hosting',
                type: 'choice',
                description: "Send events to api.eu.intercom.com, if you are using Intercom's European Data Hosting.",
                default: 'No',
                required: false,
                secret: false,
                choices: [
                    {
                        value: 'Yes',
                        label: 'Yes',
                    },
                    {
                        value: 'No',
                        label: 'No',
                    },
                ],
            },
        ],
    },
}
