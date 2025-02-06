import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha',
    type: 'transformation',
    id: 'template-remove-null-properties',
    name: 'Remove Null Properties',
    description:
        'This transformation removes null properties at all levels of the event properties object, including nested objects and arrays.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `
// Check if the event has properties
if (empty(event.properties)) {
    return event
}

let returnEvent := event

// Helper function to clean null values from objects and arrays
fun cleanNullValues(value) {
    // Return early if value is null
    if (value = null) {
        return null
    }
    
    // Handle arrays
    let valueKeys := keys(value)
    if (notEmpty(valueKeys) and has(valueKeys, '1')) {  // Hog arrays are 1-based
        let cleanArr := []
        for (let item in value) {
            let cleanItem := cleanNullValues(item)
            if (cleanItem != null) {
                cleanArr := arrayPushBack(cleanArr, cleanItem)
            }
        }
        return cleanArr
    }
    
    // Handle objects
    if (notEmpty(valueKeys)) {
        let cleanObj := {}
        for (let key in valueKeys) {
            let cleanVal := cleanNullValues(value[key])
            if (cleanVal != null) {
                cleanObj[key] := cleanVal
            }
        }
        return cleanObj
    }
    
    // Return value as is for other types
    return value
}

returnEvent.properties := cleanNullValues(event.properties)
return returnEvent
    `,
    inputs_schema: [],
}
