import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha',
    type: 'transformation',
    id: 'template-remove-null-properties',
    name: 'Remove Null Properties',
    description:
        'This transformation removes null properties at all levels of the event properties object (up to 10 levels deep), including nested objects and arrays.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `
// Check if the event has properties
if (empty(event.properties)) {
    return event
}

let returnEvent := event
let MAX_DEPTH := 10
let maxDepthReached := false

// Helper function to clean null values from objects and arrays
fun cleanNullValues(value, depth) {
    // Return early if max depth reached or value is null
    if (depth > MAX_DEPTH) {
        maxDepthReached := true
        return value
    }
    
    if (value = null) {
        return null
    }
    
    // Handle arrays
    let valueKeys := keys(value)
    if (notEmpty(valueKeys) and has(valueKeys, '1')) {  // Hog arrays are 1-based
        let cleanArr := []
        for (let item in value) {
            let cleanItem := cleanNullValues(item, depth + 1)
            if (maxDepthReached) {
                return value
            }
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
            let cleanVal := cleanNullValues(value[key], depth + 1)
            if (maxDepthReached) {
                return value
            }
            if (cleanVal != null) {
                cleanObj[key] := cleanVal
            }
        }
        return cleanObj
    }
    
    // Return value as is for other types
    return value
}

let result := cleanNullValues(event.properties, 1)
if (maxDepthReached) {
    print('Maximum nesting depth reached, returning original event')
    return event
}

returnEvent.properties := result
return returnEvent
    `,
    inputs_schema: [],
}
