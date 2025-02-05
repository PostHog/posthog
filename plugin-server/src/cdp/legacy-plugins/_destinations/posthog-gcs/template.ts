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
        id: 'plugin-https://github.com/PostHog/posthog-gcs-plugin',
        name: 'GCS Export',
        description: 'Sends events to GCS on ingestion.',
        icon_url: 'https://raw.githubusercontent.com/PostHog/posthog-gcs-plugin/main/logo.png',
        category: [],
        hog: 'return event',
        inputs_schema: [
            {
                key: 'googleCloudKeyJson',
                description: '',
                type: 'attachment',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'bucketName',
                description: 'Bucket name',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'exportEventsToIgnore',
                description: 'Comma separated list of events to ignore',
                type: 'string',
                default: '$feature_flag_called',
                required: true,
                secret: true,
            },
        ],
    },
}
