import { processEvent } from '.'

import { LegacyTransformationPlugin } from '../../types'

// NOTE: This is a deprecated plugin and should never be shown to new users
export const posthogPluginGeoip: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'stable',
        type: 'transformation',
        id: 'plugin-posthog-plugin-geoip',
        name: 'GeoIP',
        description: 'Enrich events with GeoIP data',
        icon_url: '/static/transformations/geoip.png',
        category: ['Custom'],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [],
    },
}
