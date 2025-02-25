import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'transformation',
    id: 'template-property-filter',
    name: 'Property Filter',
    description: 'Remove properties from events, with optional filtering in $set and $set_once properties.',
    icon_url: '/static/hedgehog/builder-hog-02.png',
    category: ['Custom'],
    hog: `
// Get the properties to filter from inputs and split by comma
let propertiesToFilter := []
if (notEmpty(inputs.propertiesToFilter)) {
    propertiesToFilter := splitByString(',', inputs.propertiesToFilter)
}

let includeSetProperties := inputs.includeSetProperties
let includeSetOnceProperties := inputs.includeSetOnceProperties

if (empty(propertiesToFilter)) {
    return event
}

// Helper function to check if property names match
fun propertyNamesMatch(a, b) {
    // Always do exact matches
    return trim(a) = trim(b)
}

// Helper function to filter properties from an object
fun filterObject(obj) {
    if (obj = null) {
        return null
    }
    
    if (typeof(obj) != 'object') {
        return obj
    }
    
    let result := {}
    let objKeys := keys(obj)
    
    for (let key in objKeys) {
        let shouldKeep := true
        
        for (let propToFilter in propertiesToFilter) {
            if (propertyNamesMatch(key, propToFilter)) {
                shouldKeep := false
            }
        }
        
        if (shouldKeep) {
            let value := obj[key]
            // Recursively filter nested objects
            if (typeof(value) = 'object' and value != null) {
                result[key] := filterObject(value)
            } else {
                result[key] := value
            }
        }
    }
    
    return result
}

// Helper function to filter properties recursively, but only in regular properties
fun filterProperties(obj) {
    if (obj = null) {
        return null
    }
    
    if (typeof(obj) != 'object') {
        return obj
    }
    
    let result := {}
    let objKeys := keys(obj)
    
    for (let key in objKeys) {
        let shouldKeep := true
        
        for (let propToFilter in propertiesToFilter) {
            if (propertyNamesMatch(key, propToFilter)) {
                shouldKeep := false
            }
        }
        
        if (shouldKeep) {
            let value := obj[key]
            if (key = '$set') {
                if (includeSetProperties) {
                    result[key] := filterObject(value)  // Use filterObject for $set
                } else {
                    result[key] := value
                }
            } else if (key = '$set_once') {
                if (includeSetOnceProperties) {
                    result[key] := filterObject(value)  // Use filterObject for $set_once
                } else {
                    result[key] := value
                }
            } else if (typeof(value) = 'object' and value != null) {
                result[key] := filterProperties(value)
            } else {
                result[key] := value
            }
        }
    }
    
    return result
}

// Create a copy of the event
let returnEvent := {}

// Copy non-filtered top-level properties
let eventKeys := keys(event)
for (let key in eventKeys) {
    let shouldKeep := true
    for (let propToFilter in propertiesToFilter) {
        if (propertyNamesMatch(key, propToFilter)) {
            shouldKeep := false
        }
    }
    
    if (shouldKeep) {
        if (key = 'properties') {
            returnEvent.properties := filterProperties(event.properties)
        } else {
            returnEvent[key] := event[key]
        }
    }
}

return returnEvent
`,
    inputs_schema: [
        {
            key: 'propertiesToFilter',
            type: 'string',
            label: 'Properties to Filter',
            description: 'Comma-separated list of properties to filter (e.g. "ip,distinct_id,$ip")',
            default: '$ip',
            secret: false,
            required: true,
        },
        {
            key: 'includeSetProperties',
            type: 'boolean',
            label: 'Include $set properties',
            description: 'If enabled, will also remove matching properties from $set object',
            default: false,
            required: false,
        },
        {
            key: 'includeSetOnceProperties',
            type: 'boolean',
            label: 'Include $set_once properties',
            description: 'If enabled, will also remove matching properties from $set_once object',
            default: false,
            required: false,
        },
    ],
}
