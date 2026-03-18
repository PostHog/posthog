import { LegacyTransformationPlugin } from '../../types'
import { processEvent } from './dist'
import { setupPlugin } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const posthogRouteCensorPlugin: LegacyTransformationPlugin = {
    processEvent,
    setupPlugin: setupPlugin as any,
    template: {
        free: true,
        status: 'deprecated',
        type: 'transformation',
        id: 'plugin-posthog-route-censor-plugin',
        name: 'Route Censor',
        description: 'Removes segments of URLs based on route patterns.',
        icon_url: '/static/hedgehog/builder-hog-01.png',
        category: ['Custom'],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [
            {
                key: 'routes',
                templating: false,
                label: 'List of routes following the React Router route patterns.',
                description:
                    '[Example Here](https://github.com/ava-labs/posthog-route-censor-plugin/blob/main/src/assets/exampleRoutes.json).  See package [README](https://github.com/ava-labs/posthog-route-censor-plugin) for more details.',
                type: 'json',
                required: true,
            },
            {
                key: 'properties',
                templating: false,
                label: 'List of properties to censor',
                type: 'string',
                default: '$current_url,$referrer,$pathname,$initial_current_url,initial_pathname,initial_referrer',
                description: 'Separate properties with commas, without using spaces, like so: `foo,bar,$baz`',
                required: false,
            },
            {
                key: 'set_properties',
                templating: false,
                label: 'List of $set properties to censor',
                type: 'string',
                default: '$initial_current_url,$initial_pathname,$initial_referrer',
                description: 'Separate properties with commas, without using spaces, like so: `foo,bar,$baz`',
                required: false,
            },
            {
                key: 'set_once_properties',
                templating: false,
                label: 'List of $set_once properties to censor',
                type: 'string',
                default: '$initial_current_url,$initial_pathname,$initial_referrer',
                description: 'Separate properties with commas, without using spaces, like so: `foo,bar,$baz`',
                required: false,
            },
        ],
    },
}
