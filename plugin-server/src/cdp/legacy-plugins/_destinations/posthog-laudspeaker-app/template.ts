import { LegacyDestinationPlugin } from '../../types'
import { onEvent, setupPlugin } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const laudspeakerPlugin: LegacyDestinationPlugin = {
    setupPlugin: setupPlugin as any,
    onEvent,
    template: {
        free: false,
        status: 'deprecated',
        type: 'destination',
        id: 'plugin-posthog-laudspeaker-app',
        name: 'Laudspeaker',
        description: 'Send event data to Laudspeaker',
        icon_url: 'https://raw.githubusercontent.com/laudspeaker/laudspeaker-posthog-plugin/master/logo.png',
        category: [],
        hog: 'return event',
        inputs_schema: [
            {
                key: 'dataPlaneUrl',
                description: 'Provide Laudspeaker API URL.',
                type: 'string',
                default: 'https://api.laudspeaker.com/events/posthog',
                required: true,
                secret: true,
            },
            {
                key: 'writeKey',
                description: 'Provide API key for your Laudspeaker account found on the settings page.',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'phEmail',
                description: 'Provide attribute name for email.',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'phPhoneNumber',
                description: 'Provide attribute name for phone number.',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'phDeviceToken',
                description: 'Provide attribute name for firebase device token',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'phCustom',
                description: 'Provide attribute name for your custom field.',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
        ],
    },
}
