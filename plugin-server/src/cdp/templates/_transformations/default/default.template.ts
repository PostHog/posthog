import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'beta',
    type: 'transformation',
    id: 'template-blank-transformation',
    name: 'Custom transformation',
    description: 'This is a starter template for custom transformations',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `
// This is a blank template for custom transformations
// The function receives 'event' as a global object and expects it to be returned
// If you return null the event will be dropped and not ingested into your posthog instance
return event
    `,
    inputs_schema: [],
}
