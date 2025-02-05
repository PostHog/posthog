import { HogFunctionTemplate } from '../../../templates/types'

// NOTE: This is a deprecated plugin and should never be shown to new users
export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-advanced-geoip',
    name: 'Advanced GeoIP',
    description:
        'This plugin will add advanced geoip properties to your events. You will not be billed for any events that this plugin drops.',
    icon_url: 'https://raw.githubusercontent.com/posthog/advanced-geoip-plugin/main/logo.png',
    category: ['Custom'],
    hog: `return event`,
    inputs_schema: [
        {
            key: 'discardIp',
            templating: false,
            label: 'Discard IP addresses after GeoIP?',
            type: 'choice',
            choices: [
                { value: 'true', label: 'true' },
                { value: 'false', label: 'false' },
            ],
            description: 'Whether IP addresses should be discarded after doing GeoIP lookup.',
            required: true,
        },
        {
            key: 'discardLibs',
            templating: false,
            label: 'Discard GeoIP for libraries',
            type: 'string',
            description:
                'Comma-separated list of libraries ($lib) for which GeoIP should be ignored (e.g. `posthog-node,posthog-python`)',
            required: false,
        },
    ],
}
