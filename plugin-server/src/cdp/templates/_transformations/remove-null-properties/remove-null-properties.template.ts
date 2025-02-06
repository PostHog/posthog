import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha',
    type: 'transformation',
    id: 'template-remove-null-properties',
    name: 'Remove Null Properties',
    description:
        'This transformation removes null properties from the event properties object. If the object nesting exceeds 3 levels, the original event is returned unchanged.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `
// Check if the event has properties
if (empty(event.properties)) {
    return event
}

let returnEvent := event
let MAX_DEPTH := 3
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
    print('Object nesting exceeds maximum depth of 10 levels. Returning original event unchanged for safety.')
    return event
}

returnEvent.properties := result
return returnEvent
    `,
    inputs_schema: [],
}
