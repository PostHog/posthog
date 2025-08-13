import { LegacyDestinationPlugin } from '../../types'
import { onEvent } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const engagePlugin: LegacyDestinationPlugin = {
    onEvent,
    template: {
        free: false,
        status: 'deprecated',
        type: 'destination',
        id: 'plugin-posthog-engage-so-plugin',
        name: 'Engage',
        description: 'Send user and event data to Engage for personalized engagement.',
        icon_url: 'https://raw.githubusercontent.com/engage-so/posthog-plugin/main/logo.png',
        category: [],
        code_language: 'javascript',
        code: 'return event',
        inputs_schema: [
            {
                templating: false,
                key: 'publicKey',
                label: 'Public key',
                type: 'string',
                description: 'Get your public key from your Engage dashboard (Settings -> Account)',
                required: true,
                secret: true,
            },
            {
                templating: false,
                key: 'secret',
                label: 'Private key',
                type: 'string',
                description: 'Get your private key from your Engage dashboard (Settings -> Account)',
                required: true,
                secret: true,
            },
            {
                templating: false,
                key: 'filter',
                label: 'Event filter',
                type: 'choice',
                description:
                    'Sending events for only identified users ensures user and event data for anonymous users are not sent to Engage. However, note that if they are later identified, you will miss the leading events before identification.',
                default: 'Send events for all users',
                required: false,
                secret: false,
                choices: [
                    {
                        value: 'Send events for all users',
                        label: 'Send events for all users',
                    },
                    {
                        value: 'Only send events for identified users',
                        label: 'Only send events for identified users',
                    },
                ],
            },
        ],
    },
}
