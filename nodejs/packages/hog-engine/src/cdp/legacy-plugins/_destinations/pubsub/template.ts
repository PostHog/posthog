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
        id: 'plugin-pubsub-plugin',
        name: 'Pub/Sub Export',
        description: 'Sends events to a Pub/Sub topic on ingestion.',
        icon_url: 'https://raw.githubusercontent.com/PostHog/pubsub-plugin/master/logo.png',
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
                key: 'topicId',
                label: 'Topic ID',
                type: 'string',
                description: 'A topic will be created if it does not exist.',
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
            {
                templating: false,
                key: 'exportEventsBufferBytes',
                label: 'Maximum upload size in bytes',
                type: 'string',
                description:
                    'Default 1MB. Upload events after buffering this many of them. The value must be between 1 MB and 10 MB.',
                default: '1048576',
                required: false,
                secret: false,
            },
            {
                templating: false,
                key: 'exportEventsBufferSeconds',
                label: 'Export events at least every X seconds',
                type: 'string',
                description:
                    'Default 30 seconds. If there are events to upload and this many seconds has passed since the last upload, then upload the queued events. The value must be between 1 and 600 seconds.',
                default: '30',
                required: false,
                secret: false,
            },
        ],
    },
}
