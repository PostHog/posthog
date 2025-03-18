import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha',
    type: 'transformation',
    id: 'template-remove-null-properties',
    name: 'Remove Null Properties',
    description:
        'This transformation removes null properties from the event properties object. If the object nesting exceeds 3 levels, deeper levels will be returned unchanged.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `
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
