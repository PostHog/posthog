import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha',
    type: 'transformation',
    id: 'template-remove-null-properties',
    name: 'Remove Null Properties',
    description:
        'This transformation removes empty properties, reducing unnecessary fields in downstream destinations.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `
// Check if the event has properties
if (empty(event.properties)) {
    print('No properties found in event')
    return event
}

let returnEvent := event
let propertiesToKeep := {}

// Iterate through all properties and only keep non-null values
for (let key, value in event.properties) {
    if (value != null) {
        propertiesToKeep[key] := value
    } else {
        print('Removing null property:', key)
    }
}

returnEvent.properties := propertiesToKeep
return returnEvent
    `,
    inputs_schema: [],
}
