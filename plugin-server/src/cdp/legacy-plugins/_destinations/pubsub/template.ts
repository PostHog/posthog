import { LegacyDestinationPlugin } from '../../types'
import { onEvent, setupPlugin } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const pubsubPlugin: LegacyDestinationPlugin = {
    setupPlugin: setupPlugin as any,
    onEvent,
    template: {
        free: false,
        status: 'deprecated',
        type: 'destination',
        id: 'plugin-https://github.com/PostHog/pubsub-plugin',
        name: 'Pub/Sub Export',
        description: 'Sends events to a Pub/Sub topic on ingestion.',
        icon_url: 'https://raw.githubusercontent.com/PostHog/pubsub-plugin/master/logo.png',
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
                key: 'topicId',
                description: 'A topic will be created if it does not exist.',
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
            {
                key: 'exportEventsBufferBytes',
                description:
                    'Default 1MB. Upload events after buffering this many of them. The value must be between 1 MB and 10 MB.',
                type: 'string',
                default: '1048576',
                required: true,
                secret: true,
            },
            {
                key: 'exportEventsBufferSeconds',
                description:
                    'Default 30 seconds. If there are events to upload and this many seconds has passed since the last upload, then upload the queued events. The value must be between 1 and 600 seconds.',
                type: 'string',
                default: '30',
                required: true,
                secret: true,
            },
        ],
    },
}
