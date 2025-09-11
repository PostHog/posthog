import { LegacyDestinationPlugin } from '../../types'
import { onEvent, setupPlugin } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const gcsPlugin: LegacyDestinationPlugin = {
    setupPlugin: setupPlugin as any,
    onEvent,
    template: {
        free: false,
        status: 'deprecated',
        type: 'destination',
        id: 'plugin-posthog-gcs-plugin',
        name: 'GCS Export',
        description: 'Sends events to GCS on ingestion.',
        icon_url: 'https://raw.githubusercontent.com/PostHog/posthog-gcs-plugin/main/logo.png',
        category: [],
        code_language: 'javascript',
        code: 'return event',
        inputs_schema: [
            {
                templating: false,
                key: 'googleCloudKeyJson',
                label: 'JSON file with your google cloud key',
                type: 'json',
                required: true,
                secret: true,
            },
            {
                templating: false,
                key: 'bucketName',
                label: 'Table ID',
                type: 'string',
                description: 'Bucket name',
                required: true,
                secret: false,
            },
            {
                templating: false,
                key: 'exportEventsToIgnore',
                label: 'Events to ignore',
                type: 'string',
                description: 'Comma separated list of events to ignore',
                default: '$feature_flag_called',
                required: false,
                secret: false,
            },
        ],
    },
}
