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
                label: 'Laudspeaker API URL',
                type: 'string',
                description: 'Provide Laudspeaker API URL.',
                default: 'https://api.laudspeaker.com/events/posthog',
                required: true,
                secret: false,
            },
            {
                key: 'writeKey',
                label: 'Laudspeaker API Key',
                type: 'string',
                description: 'Provide API key for your Laudspeaker account found on the settings page.',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'phEmail',
                label: 'Email attribute name',
                type: 'string',
                description: 'Provide attribute name for email.',
                default: '',
                required: false,
                secret: false,
            },
            {
                key: 'phPhoneNumber',
                label: 'Phone number attribute name',
                type: 'string',
                description: 'Provide attribute name for phone number.',
                default: '',
                required: false,
                secret: false,
            },
            {
                key: 'phDeviceToken',
                label: 'Device Token attribute name',
                type: 'string',
                description: 'Provide attribute name for firebase device token',
                default: '',
                required: false,
                secret: false,
            },
            {
                key: 'phCustom',
                type: 'string',
                description: 'Provide attribute name for your custom field.',
                default: '',
                required: false,
                secret: false,
            },
        ],
    },
}
