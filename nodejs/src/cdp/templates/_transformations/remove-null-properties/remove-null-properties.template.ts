import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'transformation',
    id: 'template-remove-null-properties',
    name: 'Remove Null Properties',
    description:
        'This transformation removes null properties from the event properties object. If the object nesting exceeds 3 levels, deeper levels will be returned unchanged.',
    icon_url: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
// Check if the event has properties
if (empty(event.properties)) {
    return event
}

let returnEvent := event
returnEvent.properties := cleanNullValues(event.properties)
return returnEvent
    `,
    inputs_schema: [],
}
