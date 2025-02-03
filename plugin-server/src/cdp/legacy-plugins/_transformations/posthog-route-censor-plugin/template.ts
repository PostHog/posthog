import { HogFunctionTemplate } from '../../../templates/types'

// NOTE: This is a deprecated plugin and should never be shown to new users
export const template: HogFunctionTemplate = {
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-posthog-route-censor-plugin',
    name: 'Route Censor',
    description: 'Removes segments of URLs based on route patterns.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `return event`,
    inputs_schema: [
        {
            key: 'routes',
            templating: false,
            label: 'List of routes following the React Router route patterns.',
            description:
                '[Example Here](https://github.com/ava-labs/posthog-route-censor-plugin/blob/main/src/assets/exampleRoutes.json).  See package [README](https://github.com/ava-labs/posthog-route-censor-plugin) for more details.',
            type: 'string',
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
}
