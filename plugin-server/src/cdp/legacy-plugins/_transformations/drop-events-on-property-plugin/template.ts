import { HogFunctionTemplate } from '../../../templates/types'

// NOTE: This is a deprecated plugin and should never be shown to new users
export const template: HogFunctionTemplate = {
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-drop-events-on-property-plugin',
    name: 'Drop Events Based On Property',
    description:
        'This plugin will drop any events that have a specific key. If you supply a value, it will drop any event with the combination of they key and the value. You will not be billed for any events that this plugin drops.',
    icon_url: 'https://raw.githubusercontent.com/posthog/drop-events-on-property-plugin/main/logo.png',
    category: ['Custom'],
    hog: `return event`,
    inputs_schema: [
        {
            key: 'property_key',
            templating: false,
            description:
                'Which property key to filter on. If you do not specify a value, all events with this key will be dropped.',
            label: 'Property key to filter on',
            type: 'string',
            required: true,
        },
        {
            key: 'property_values',
            templating: false,
            description: 'Which value to match to drop events. Split multiple values by comma to filter.',
            label: 'Property value to filter on',
            type: 'string',
            required: false,
        },
    ],
}
