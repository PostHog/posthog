import { LegacyDestinationPlugin } from '../../types'
import { onEvent, setupPlugin } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const rudderstackPlugin: LegacyDestinationPlugin = {
    setupPlugin: setupPlugin as any,
    onEvent,
    template: {
        free: false,
        status: 'deprecated',
        type: 'destination',
        id: 'plugin-rudderstack-posthog-plugin',
        name: 'RudderStack',
        description: 'Send event data to RudderStack',
        icon_url: 'https://raw.githubusercontent.com/rudderlabs/rudderstack-posthog-plugin/main/logo.png',
        category: [],
        hog: 'return event',
        inputs_schema: [
            {
                key: 'dataPlaneUrl',
                label: 'RudderStack Server URL',
                type: 'string',
                description: 'Provide RudderStack server url, append v1/batch path',
                default: 'https://hosted.rudderlabs.com/v1/batch',
                required: true,
                secret: false,
            },
            {
                key: 'writeKey',
                label: 'RudderStack Source Writekey',
                type: 'string',
                description: 'Provide source writekey',
                default: '',
                required: true,
                secret: true,
            },
        ],
    },
}
