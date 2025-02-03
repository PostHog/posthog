import { HogFunctionTemplate } from '../../../templates/types'

// NOTE: This is a deprecated plugin and should never be shown to new users
export const template: HogFunctionTemplate = {
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-posthog-plugin-geoip',
    name: 'GeoIP',
    description: '',
    icon_url: '/static/transformations/geoip.png',
    category: ['Custom'],
    hog: `return event`,
    inputs_schema: [],
}
