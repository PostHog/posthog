import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'beta',
    type: 'transformation',
    id: 'template-drop-events',
    name: 'Drop Events',
    description: 'Drop events based on defined filters',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `
    // This transformation drops events based on defined filters
    // Information about setting up filters correctly can be found here: https://posthog.com/docs/cdp/transformations/drop-events
    // Events matching the filters will be dropped (return null)
    return null`,
    inputs_schema: [],
}
