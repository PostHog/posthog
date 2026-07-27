import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'transformation',
    id: 'template-blank-transformation',
    name: 'Custom transformation',
    description: 'This is a starter template for custom transformations',
    icon_url: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
// This is a blank template for custom transformations
// The function receives 'event' as a global object and expects it to be returned
// If you return null the event will be dropped and not ingested into your posthog instance
// Check out our docs: https://posthog.com/docs/cdp/transformations/customizing-transformations
let returnEvent := event
returnEvent.properties.$example_added_property := 'example'
return returnEvent
    `,
    inputs_schema: [],
}
